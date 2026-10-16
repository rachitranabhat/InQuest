import clsx, { type ClassValue } from "clsx";

export function cx(...v: ClassValue[]): string {
  return clsx(v);
}
