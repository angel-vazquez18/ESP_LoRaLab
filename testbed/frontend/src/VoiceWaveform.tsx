export type WaveBin = { min: number; max: number };

export default function VoiceWaveform({
  bins,
  label,
}: {
  bins: WaveBin[];
  label: string;
}) {
  return (
    <svg
      className="audio-waveform"
      viewBox="0 0 640 120"
      role="img"
      aria-label={label}
    >
      <line x1="0" y1="60" x2="640" y2="60" />
      {bins.map((bin, index) => {
        const x = ((index + 0.5) * 640) / bins.length;
        return (
          <line
            key={index}
            className="audio-wave-bin"
            x1={x}
            x2={x}
            y1={60 - bin.max * 55}
            y2={60 - bin.min * 55}
          />
        );
      })}
    </svg>
  );
}
