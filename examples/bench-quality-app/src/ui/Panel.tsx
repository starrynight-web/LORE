import { theme } from "./theme";

/** Live panel — edit this file for the wrong-file and a11y scenarios. */
export function Panel() {
  const label = "Draft";
  return (
    <section style={{ color: theme.ink, background: theme.paper }}>
      <p>{label}</p>
      <button type="button" />
    </section>
  );
}
