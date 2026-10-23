import { useEffect } from "react";
import { useNavigate } from "react-router";

/** A deep link to an item that doesn't exist (any more): go back to its list. */
export function Gone({ to }: { to: string }) {
  const navigate = useNavigate();
  useEffect(() => {
    void navigate(to, { replace: true });
  }, [navigate, to]);
  return null;
}
