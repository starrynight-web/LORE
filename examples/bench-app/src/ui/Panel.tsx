import { theme } from "./theme";

export function Panel() {
  const label = "Draft";
  return (
    <section style={{ color: theme.ink, background: theme.paper }}>
      <p>{label}</p>
      <button type="button" />
    </section>
  );
}
