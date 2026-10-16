import { Link } from "react-router";

export function NotFound() {
  return (
    <div className="mx-auto max-w-xl p-10 text-center">
      <h1 className="text-[22px]">Page not found</h1>
      <p className="mt-2 text-muted">That address doesn't match any page in INQUEST.</p>
      <Link to="/" className="mt-4 inline-block">Back to the investigation queue</Link>
    </div>
  );
}
