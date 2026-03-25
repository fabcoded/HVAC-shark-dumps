from pathlib import Path
import pandas as pd
import numpy as np

TB_US = 1e6 / 48000
IDLE_US = 3000
MIN_EDGE_US = 5.0


def decode_track_independent(times_s, raw_signal, source_name):
    """Decode one digital track independently."""
    raw_signal = raw_signal.astype(np.int8)
    diff = np.diff(raw_signal)
    edge_idx = np.concatenate([[0], np.where(diff != 0)[0] + 1])
    edge_t_us = times_s[edge_idx] * 1e6
    edge_lvl = raw_signal[edge_idx]

    def sig_at(t_us):
        i = int(np.searchsorted(edge_t_us, t_us, side='right')) - 1
        i = max(0, min(i, len(edge_lvl) - 1))
        return 1 - int(edge_lvl[i])

    bursts = []
    in_burst = False
    t0 = None
    for k in range(len(edge_t_us) - 1):
        t = edge_t_us[k]
        dur = edge_t_us[k + 1] - t
        lv = 1 - int(edge_lvl[k])
        if lv == 0 and dur > IDLE_US:
            if in_burst:
                bursts.append((t0, t))
            in_burst = False
            t0 = None
        elif not in_burst and dur >= MIN_EDGE_US:
            t0 = t
            in_burst = True
    if in_burst:
        bursts.append((t0, edge_t_us[-1]))

    def uart_decode(bits, uart_off):
        phys = []
        i = uart_off
        while i + 9 < len(bits):
            if bits[i] != 0:
                i += 1
                continue
            data = bits[i + 1:i + 9]
            if bits[i + 9] != 1:
                i += 1
                continue
            phys.append(sum(data[j] << j for j in range(8)))
            i += 10
        return phys

    def nibble_decode(phys, nib_off):
        src = phys[nib_off:]
        out = []
        for i in range(0, len(src) - 1, 2):
            a, b = src[i], src[i + 1]
            na = ((a >> 0) & 1) | (((a >> 2) & 1) << 1) | (((a >> 4) & 1) << 2) | (((a >> 6) & 1) << 3)
            nb = ((b >> 0) & 1) | (((b >> 2) & 1) << 1) | (((b >> 4) & 1) << 2) | (((b >> 6) & 1) << 3)
            out.append((nb | (na << 4)) ^ 0xFF)
        return out

    frames = []
    for bi, (t0, t1) in enumerate(bursts):
        best = None
        for phase_us in np.linspace(-0.75 * TB_US, 0.75 * TB_US, 31):
            start = t0 + phase_us
            nbits = int(max(0, (t1 - start)) / TB_US) + 24
            if nbits < 20:
                continue
            bits = [sig_at(start + k * TB_US) for k in range(nbits)]
            for uart_off in range(10):
                phys = uart_decode(bits, uart_off)
                if len(phys) < 2:
                    continue
                for nib_off in (0, 1):
                    logical = nibble_decode(phys, nib_off)
                    if len(logical) < 3:
                        continue
                    crc_calc = (-sum(logical[1:-1])) % 256
                    crc_ok = crc_calc == logical[-1]
                    first_aa = int(logical[0] == 0xAA)
                    score = (int(crc_ok), len(logical), first_aa)
                    cand = {
                        'score': score,
                        'source': source_name,
                        'burst_idx': bi,
                        'timestamp_s': round(t0 / 1e6, 9),
                        'phase_us': round(float(phase_us), 3),
                        'uart_off': int(uart_off),
                        'nib_off': int(nib_off),
                        'cmd': f'{logical[1]:02X}' if len(logical) > 1 else '',
                        'len': len(logical),
                        'crc_ok': bool(crc_ok),
                        'crc_calc': f'{crc_calc:02X}',
                        'frame_hex': ' '.join(f'{v:02X}' for v in logical),
                        '_log': logical,
                        '_t_us': t0,
                    }
                    if best is None or cand['score'] > best['score']:
                        best = cand
        if best is not None:
            frames.append(best)
    return frames


def strip_hidden(frames):
    return pd.DataFrame([{k: v for k, v in f.items() if not k.startswith('_') and k != 'score'} for f in frames])


def main(input_csv='digital3.csv', outdir='output'):
    outdir = Path(outdir)
    outdir.mkdir(exist_ok=True)

    df = pd.read_csv(input_csv)
    df.columns = ['time', 'ch6', 'ch7']
    times = df['time'].to_numpy()

    ch6_frames = decode_track_independent(times, df['ch6'].to_numpy(), 'CH6')
    ch7_frames = decode_track_independent(times, df['ch7'].to_numpy(), 'CH7')

    byte_time_us = 10 * TB_US
    ch6_minus_ch7 = []
    for f6 in ch6_frames:
        dup = any(abs(f6['_t_us'] - f7['_t_us']) <= byte_time_us and f6['_log'] == f7['_log'] for f7 in ch7_frames)
        if not dup:
            ch6_minus_ch7.append(dict(f6, source='CH6_MINUS_CH7'))

    strip_hidden(ch6_frames).to_csv(outdir / 'ch6_independent.csv', index=False)
    strip_hidden(ch7_frames).to_csv(outdir / 'ch7_independent.csv', index=False)
    strip_hidden(ch6_minus_ch7).to_csv(outdir / 'ch6_minus_ch7_independent.csv', index=False)

    return {
        'ch6_total': len(ch6_frames),
        'ch6_crc_ok': sum(1 for f in ch6_frames if f['crc_ok']),
        'ch7_total': len(ch7_frames),
        'ch7_crc_ok': sum(1 for f in ch7_frames if f['crc_ok']),
        'sub_total': len(ch6_minus_ch7),
        'sub_crc_ok': sum(1 for f in ch6_minus_ch7 if f['crc_ok']),
        'removed_duplicates': len(ch6_frames) - len(ch6_minus_ch7),
    }


if __name__ == '__main__':
    print(main())
