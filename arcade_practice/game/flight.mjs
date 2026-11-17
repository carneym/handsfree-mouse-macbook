export const clamp = (n, low, high) => Math.max(low, Math.min(high, n));

export function courseAt(z) {
  return { x: Math.sin(z * .009) * 4.2 + Math.sin(z * .021) * 1.2,
           y: Math.sin(z * .012 + .4) * 2.4 };
}

export class Flight {
  constructor() { this.reset(); }
  reset({ mode = 'practice', speed = 28, difficulty = 'relaxed' } = {}) {
    this.mode = mode;
    this.speed = clamp(Number(speed) || 28, 16, 58);
    this.difficulty = difficulty;
    this.radius = difficulty === 'precise' ? [2.1, 1.55] : difficulty === 'balanced' ? [2.8, 2] : [3.6, 2.6];
    this.distance = this.elapsed = this.score = this.hits = this.misses = this.streak = this.bestStreak = 0;
    this.player = { x: 0, y: 0, vx: 0, vy: 0 };
    this.target = { x: 0, y: 0 };
    this.nextGate = 1;
    this.finished = false;
    this.gates = Array.from({length: 18}, () => this.makeGate());
  }
  makeGate() {
    const id = this.nextGate++, z = id * 52 + 30;
    return { id, z, ...courseAt(z), rx: this.radius[0], ry: this.radius[1] };
  }
  steer(x, y) {
    if (!Number.isFinite(x) || !Number.isFinite(y)) return;
    this.target.x = clamp(x, -1, 1) * 8;
    this.target.y = clamp(y, -1, 1) * 5;
  }
  update(dt) {
    if (this.finished || !Number.isFinite(dt) || dt <= 0) return [];
    dt = Math.min(dt, .05); // A delayed frame never teleports through the course.
    const remaining = this.mode === 'trial' ? 60 - this.elapsed : Infinity;
    dt = Math.min(dt, Math.max(0, remaining));
    const old = { ...this.player }, oldDistance = this.distance;
    const blend = 1 - Math.exp(-dt / .19);
    this.player.x += (this.target.x - this.player.x) * blend;
    this.player.y += (this.target.y - this.player.y) * blend;
    this.player.vx = dt ? (this.player.x-old.x)/dt : 0;
    this.player.vy = dt ? (this.player.y-old.y)/dt : 0;
    this.elapsed += dt;
    this.distance += this.speed * dt;
    const events = [];
    while (this.gates[0].z <= this.distance) {
      const gate = this.gates.shift();
      const fraction = clamp((gate.z-oldDistance)/(this.distance-oldDistance || 1), 0, 1);
      const px = old.x + (this.player.x-old.x)*fraction;
      const py = old.y + (this.player.y-old.y)*fraction;
      const error = ((px-gate.x)/gate.rx)**2 + ((py-gate.y)/gate.ry)**2;
      const hit = error <= 1;
      if (hit) {
        this.hits++; this.streak++;
        this.bestStreak = Math.max(this.bestStreak, this.streak);
        this.score += 100 + Math.min(this.streak-1, 10) * 10;
      } else { this.misses++; this.streak = 0; }
      events.push({ hit, error, gate });
      this.gates.push(this.makeGate());
    }
    if (this.mode === 'trial' && this.elapsed >= 60-1e-8) this.finished = true;
    return events;
  }
  get accuracy() { return this.hits+this.misses ? Math.round(this.hits/(this.hits+this.misses)*100) : null; }
}
