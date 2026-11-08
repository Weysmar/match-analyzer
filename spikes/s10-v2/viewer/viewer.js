// Spike of step 10, T10.5: a Canvas player for the 2D view's document. Throwaway code.
// Reads `window.VIEW` (the document of measure_view.py), draws the field from above, interpolates
// between samples, and reports frames per second.

const FIELD = { x: 4096, y: 5120, goalDepth: 880, goalHalfWidth: 893 };
const COLORS = { blue: "#2f80ed", orange: "#f2994a", ball: "#e0e0e0", line: "#3a4256", grass: "#152033" };

const doc = window.VIEW;
const players = Object.entries(doc.players).map(([idx, p]) => ({ idx, ...p }));
const last = doc.t.length - 1;
const durationMs = doc.t[last];

const canvas = document.getElementById("field");
const ctx = canvas.getContext("2d");
const play = document.getElementById("play");
const speed = document.getElementById("speed");
const scrub = document.getElementById("scrub");
const clock = document.getElementById("clock");
const fpsOut = document.getElementById("fps");
scrub.max = String(durationMs);

let now = 0;
let playing = false;
let rate = 1;
let lastTick = performance.now();
let frames = 0;
let fpsSince = performance.now();

function size() {
  const ratio = window.devicePixelRatio || 1;
  const box = canvas.parentElement.getBoundingClientRect();
  // The field stands upright: blue defends the bottom.
  const height = Math.min(box.width * ((FIELD.y + FIELD.goalDepth) / FIELD.x), window.innerHeight * 0.75);
  const width = height * (FIELD.x / (FIELD.y + FIELD.goalDepth));
  canvas.width = Math.round(width * ratio);
  canvas.height = Math.round(height * ratio);
  // CSSOM, not a style attribute: the site's security policy refuses those (A65).
  canvas.style.width = `${width}px`;
  canvas.style.height = `${height}px`;
}

function toScreen(x, y) {
  const sx = canvas.width / (2 * FIELD.x);
  const sy = canvas.height / (2 * (FIELD.y + FIELD.goalDepth));
  return [(x + FIELD.x) * sx, (FIELD.y + FIELD.goalDepth - y) * sy];
}

function sampleAt(ms) {
  // Index of the sample at or before `ms`, and how far towards the next.
  const step = 1000 / doc.rate;
  const i = Math.min(last - 1, Math.max(0, Math.floor(ms / step)));
  const f = Math.min(1, Math.max(0, (ms - doc.t[i]) / Math.max(1, doc.t[i + 1] - doc.t[i])));
  return [i, f];
}

function lerp(values, i, f) {
  const a = values[i];
  const b = values[i + 1];
  if (a === null || b === null) return a ?? b;
  return a + (b - a) * f;
}

function lerpAngle(values, i, f) {
  const a = values[i];
  const b = values[i + 1];
  if (a === null || b === null) return a ?? b;
  const d = ((b - a + 540) % 360) - 180;
  return a + d * f;
}

function drawField() {
  ctx.fillStyle = COLORS.grass;
  ctx.fillRect(0, 0, canvas.width, canvas.height);
  ctx.strokeStyle = COLORS.line;
  ctx.lineWidth = Math.max(1, canvas.width / 400);
  const [x0, y0] = toScreen(-FIELD.x, FIELD.y);
  const [x1, y1] = toScreen(FIELD.x, -FIELD.y);
  ctx.strokeRect(x0, y0, x1 - x0, y1 - y0);
  const [, ym] = toScreen(0, 0);
  ctx.beginPath();
  ctx.moveTo(x0, ym);
  ctx.lineTo(x1, ym);
  ctx.stroke();
  for (const side of [1, -1]) {
    const [gx0, gy0] = toScreen(-FIELD.goalHalfWidth, side * (FIELD.y + (side > 0 ? FIELD.goalDepth : 0)));
    const [gx1, gy1] = toScreen(FIELD.goalHalfWidth, side * (FIELD.y + (side > 0 ? 0 : FIELD.goalDepth)));
    ctx.fillStyle = side > 0 ? "rgba(242,153,74,0.25)" : "rgba(47,128,237,0.25)";
    ctx.fillRect(gx0, gy0, gx1 - gx0, gy1 - gy0);
  }
}

function draw() {
  drawField();
  const [i, f] = sampleAt(now);
  const unit = canvas.width / (2 * FIELD.x);
  for (const p of players) {
    if (!p.on[i] && !p.on[i + 1]) continue;
    const x = lerp(p.x, i, f);
    const y = lerp(p.y, i, f);
    if (x === null || y === null) continue;
    const [sx, sy] = toScreen(x, y);
    const heading = (lerpAngle(p.yaw, i, f) ?? 0) * (Math.PI / 180);
    ctx.save();
    ctx.translate(sx, sy);
    ctx.rotate(-heading + Math.PI / 2);
    ctx.fillStyle = p.team === 0 ? COLORS.blue : COLORS.orange;
    ctx.fillRect(-42 * unit * 1.6, -59 * unit * 1.6, 84 * unit * 1.6, 118 * unit * 1.6);
    ctx.restore();
    const boost = lerp(p.boost, i, f) ?? 0;
    ctx.fillStyle = "#f2c94c";
    ctx.fillRect(sx - 120 * unit, sy + 110 * unit, (240 * unit * boost) / 100, 24 * unit);
  }
  const bx = lerp(doc.ball.x, i, f);
  const by = lerp(doc.ball.y, i, f);
  const bz = lerp(doc.ball.z, i, f) ?? 93;
  if (bx !== null && by !== null) {
    const [sx, sy] = toScreen(bx, by);
    ctx.fillStyle = "rgba(0,0,0,0.35)";
    ctx.beginPath();
    ctx.arc(sx, sy, 93 * unit * 1.4, 0, Math.PI * 2);
    ctx.fill();
    ctx.fillStyle = COLORS.ball;
    ctx.beginPath();
    ctx.arc(sx, sy - (bz - 93) * unit * 0.15, 93 * unit * (1.4 + bz / 2000), 0, Math.PI * 2);
    ctx.fill();
  }
}

function format(ms) {
  const s = Math.floor(ms / 1000);
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

function tick(time) {
  const elapsed = time - lastTick;
  lastTick = time;
  if (playing) {
    now = Math.min(durationMs, now + elapsed * rate);
    if (now >= durationMs) playing = false;
    scrub.value = String(Math.round(now));
  }
  draw();
  clock.textContent = `${format(now)} / ${format(durationMs)}`;
  frames += 1;
  if (time - fpsSince >= 1000) {
    fpsOut.textContent = `${Math.round((frames * 1000) / (time - fpsSince))} img/s`;
    frames = 0;
    fpsSince = time;
  }
  requestAnimationFrame(tick);
}

play.addEventListener("click", () => {
  playing = !playing;
  play.textContent = playing ? "Pause" : "Lecture";
});
speed.addEventListener("change", () => {
  rate = Number(speed.value);
});
scrub.addEventListener("input", () => {
  now = Number(scrub.value);
});
document.addEventListener("keydown", (event) => {
  if (event.key === " ") {
    event.preventDefault();
    play.click();
  } else if (event.key === "ArrowRight") now = Math.min(durationMs, now + 5000);
  else if (event.key === "ArrowLeft") now = Math.max(0, now - 5000);
});

const goals = document.getElementById("goals");
for (const goal of doc.goals ?? []) {
  const button = document.createElement("button");
  button.type = "button";
  button.textContent = `But ${goal.team === 0 ? "bleu" : "orange"} à ${format(goal.t)}`;
  button.addEventListener("click", () => {
    now = Math.max(0, goal.t - 5000);
    scrub.value = String(now);
    playing = true;
    play.textContent = "Pause";
  });
  goals.appendChild(button);
}

window.addEventListener("resize", size);
size();
requestAnimationFrame(tick);
