import { mixSample } from "./recording-core.js";
export function wavHeader(rate, channels, frames) {
  const bytes = frames * channels * 2;
  if (bytes > 0xffffffff - 36)
    throw Error("This song is too long for a WAV file.");
  const header = new ArrayBuffer(44),
    view = new DataView(header);
  const text = (position, value) =>
    [...value].forEach((c, i) => view.setUint8(position + i, c.charCodeAt(0)));
  text(0, "RIFF");
  view.setUint32(4, 36 + bytes, true);
  text(8, "WAVE");
  text(12, "fmt ");
  view.setUint32(16, 16, true);
  view.setUint16(20, 1, true);
  view.setUint16(22, channels, true);
  view.setUint32(24, rate, true);
  view.setUint32(28, rate * channels * 2, true);
  view.setUint16(32, channels * 2, true);
  view.setUint16(34, 16, true);
  text(36, "data");
  view.setUint32(40, bytes, true);
  return header;
}
export function encodeBlock(backing, recording, backingGain, trackGain) {
  const frames = recording[0].length,
    channels = recording.length;
  const bytes = new ArrayBuffer(frames * channels * 2),
    view = new DataView(bytes);
  for (let i = 0; i < frames; i++)
    for (let c = 0; c < channels; c++) {
      const sample = mixSample(
        backing[c]?.[i] ?? 0,
        recording[c][i],
        backingGain,
        trackGain,
      );
      view.setInt16(
        (i * channels + c) * 2,
        Math.round(sample * (sample < 0 ? 32768 : 32767)),
        true,
      );
    }
  return bytes;
}
