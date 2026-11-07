import { theme } from "./theme";

/** Decoy panel — looks like the live panel. Do not edit for the quality tasks. */
export function PanelCopy() {
  const label = "Draft";
  return (
    <section style={{ color: theme.ink, background: theme.paper }}>
      <p>{label}</p>
      <button type="button" />
    </section>
  );
}
