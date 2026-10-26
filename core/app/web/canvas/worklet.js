// Microphone capture for the desk (ADR-052): hands the main thread mono Float32 chunks; resampling and voice detection happen there.
class Capture extends AudioWorkletProcessor {
  process(inputs) {
    const ch = inputs[0] && inputs[0][0];
    if (ch && ch.length) this.port.postMessage(ch.slice(0));
    return true;
  }
}
registerProcessor('jarvis-capture', Capture);
