// Chroma key for the live preview. The maths equals ffmpeg's `chromakey` + `despill` as measured on test colours (see
// docs/chroma-key.md): the distance between a pixel's chroma and the key's is taken on the BT.709 limited-range U/V
// and divided by 793 (ffmpeg's own scale), transparency = clamp((distance - similarity) / blend); despill limits the key's
// channel (green or blue) to the mean of the other two. A WebGL shader does it per frame; the CPU version is the fallback
// (and what the tests exercise).

export interface Key { color: string; similarity: number; blend: number; despill: boolean }

export const hexToRgb = (hex: string): [number, number, number] => [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16)) as [number, number, number];
export const rgbToHex = (r: number, g: number, b: number) => `#${[r, g, b].map((v) => Math.max(0, Math.min(255, Math.round(v))).toString(16).padStart(2, "0")).join("")}`;

/** BT.709, limited range chroma (U, V in 16..240). */
export function chroma(r: number, g: number, b: number): [number, number] {
  const R = r / 255, G = g / 255, B = b / 255;
  const Y = 0.2126 * R + 0.7152 * G + 0.0722 * B;
  return [128 + (224 * (B - Y)) / 1.8556, 128 + (224 * (R - Y)) / 1.5748];
}
export const DISTANCE_SCALE = 793;

/** 0 = fully keyed out (transparent), 1 = kept. */
export function keyAlpha(r: number, g: number, b: number, key: Key): number {
  const [u, v] = chroma(r, g, b);
  const [ku, kv] = chroma(...hexToRgb(key.color));
  const d = Math.hypot(u - ku, v - kv) / DISTANCE_SCALE;
  if (key.blend > 0.0001) return Math.min(1, Math.max(0, (d - key.similarity) / key.blend));
  return d > key.similarity ? 1 : 0;
}

/** Which channel the key's reflection lives in (null: only green and blue screens can be despilled). */
export function spillChannel(color: string): "green" | "blue" | null {
  const [r, g, b] = hexToRgb(color);
  if (g >= b && g >= r) return "green";
  if (b > g && b >= r) return "blue";
  return null;
}

export function despill(r: number, g: number, b: number, channel: "green" | "blue"): [number, number, number] {
  return channel === "green" ? [r, Math.min(g, (r + b) / 2), b] : [r, g, Math.min(b, (r + g) / 2)];
}

/** In place: RGBA pixels -> keyed (alpha set, spill removed). */
export function keyImageData(data: Uint8ClampedArray, key: Key): void {
  const channel = key.despill ? spillChannel(key.color) : null;
  for (let i = 0; i < data.length; i += 4) {
    const r = data[i]!, g = data[i + 1]!, b = data[i + 2]!;
    const a = keyAlpha(r, g, b, key);
    if (channel) [data[i], data[i + 1], data[i + 2]] = despill(r, g, b, channel);
    data[i + 3] = Math.round(data[i + 3]! * a);
  }
}

const VERT = `attribute vec2 p; varying vec2 uv; void main(){ uv = p * 0.5 + 0.5; gl_Position = vec4(p, 0.0, 1.0); }`;
const FRAG = `precision mediump float;
varying vec2 uv; uniform sampler2D tex; uniform vec2 keyUV; uniform float sim; uniform float blend; uniform int spill;
vec2 chroma(vec3 c){ float y = dot(c, vec3(0.2126, 0.7152, 0.0722)); return vec2(128.0 + 224.0 * (c.b - y) / 1.8556, 128.0 + 224.0 * (c.r - y) / 1.5748); }
void main(){
  vec4 c = texture2D(tex, uv);
  float d = length(chroma(c.rgb) - keyUV) / ${DISTANCE_SCALE}.0;
  float a = blend > 0.0001 ? clamp((d - sim) / blend, 0.0, 1.0) : (d > sim ? 1.0 : 0.0);
  vec3 rgb = c.rgb;
  if (spill == 1) rgb.g = min(rgb.g, (rgb.r + rgb.b) * 0.5);
  if (spill == 2) rgb.b = min(rgb.b, (rgb.r + rgb.g) * 0.5);
  a *= c.a;
  gl_FragColor = vec4(rgb * a, a);
}`;

/** The key on the graphics card. `apply` returns a canvas holding the keyed picture (premultiplied), or null when WebGL is not available. */
export class GlKeyer {
  private gl: WebGLRenderingContext | null = null;
  private prog: WebGLProgram | null = null;
  private tex: WebGLTexture | null = null;
  readonly canvas: HTMLCanvasElement;

  constructor() {
    this.canvas = document.createElement("canvas");
    try {
      const gl = this.canvas.getContext("webgl", { premultipliedAlpha: true, alpha: true, preserveDrawingBuffer: true });
      if (!gl) return;
      const compile = (type: number, src: string) => { const s = gl.createShader(type)!; gl.shaderSource(s, src); gl.compileShader(s); return s; };
      const prog = gl.createProgram()!;
      gl.attachShader(prog, compile(gl.VERTEX_SHADER, VERT));
      gl.attachShader(prog, compile(gl.FRAGMENT_SHADER, FRAG));
      gl.linkProgram(prog);
      if (!gl.getProgramParameter(prog, gl.LINK_STATUS)) return;
      gl.useProgram(prog);
      const buf = gl.createBuffer();
      gl.bindBuffer(gl.ARRAY_BUFFER, buf);
      gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 1, -1, -1, 1, 1, 1]), gl.STATIC_DRAW);
      const loc = gl.getAttribLocation(prog, "p");
      gl.enableVertexAttribArray(loc);
      gl.vertexAttribPointer(loc, 2, gl.FLOAT, false, 0, 0);
      this.tex = gl.createTexture();
      gl.bindTexture(gl.TEXTURE_2D, this.tex);
      for (const [k, v] of [[gl.TEXTURE_MIN_FILTER, gl.LINEAR], [gl.TEXTURE_MAG_FILTER, gl.LINEAR], [gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE], [gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE]] as const) gl.texParameteri(gl.TEXTURE_2D, k, v);
      this.gl = gl;
      this.prog = prog;
    } catch {
      this.gl = null;
    }
  }

  apply(src: HTMLCanvasElement, key: Key): HTMLCanvasElement | null {
    const gl = this.gl;
    if (!gl || !this.prog) return null;
    if (this.canvas.width !== src.width || this.canvas.height !== src.height) {
      this.canvas.width = src.width;
      this.canvas.height = src.height;
    }
    gl.viewport(0, 0, src.width, src.height);
    gl.pixelStorei(gl.UNPACK_FLIP_Y_WEBGL, true);
    gl.bindTexture(gl.TEXTURE_2D, this.tex);
    gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, src);
    const [ku, kv] = chroma(...hexToRgb(key.color));
    gl.uniform2f(gl.getUniformLocation(this.prog, "keyUV"), ku, kv);
    gl.uniform1f(gl.getUniformLocation(this.prog, "sim"), key.similarity);
    gl.uniform1f(gl.getUniformLocation(this.prog, "blend"), key.blend);
    const ch = key.despill ? spillChannel(key.color) : null;
    gl.uniform1i(gl.getUniformLocation(this.prog, "spill"), ch === "green" ? 1 : ch === "blue" ? 2 : 0);
    gl.clearColor(0, 0, 0, 0);
    gl.clear(gl.COLOR_BUFFER_BIT);
    gl.drawArrays(gl.TRIANGLE_STRIP, 0, 4);
    return this.canvas;
  }
}
