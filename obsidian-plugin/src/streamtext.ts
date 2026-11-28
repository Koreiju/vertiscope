/** A partial chat reply cut inside a ``` block is closed, so while it streams
 *  into the note it cannot swallow the ```chat fence below it (G-462). */
export function closeOpenFence(t: string): string {
  const F = "`".repeat(3);
  const n = t.split("\n").filter((l) => l.trim().startsWith(F)).length;
  return n % 2 ? t + "\n" + F : t;
}
