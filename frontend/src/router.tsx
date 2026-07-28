import type { MouseEvent, ReactNode } from "react";
import { useEffect, useState } from "react";
import type { ProfileRuntime } from "./profile";

export function internalPath(pathname: string, runtime: ProfileRuntime): string {
  const base = runtime.basePath.slice(0, -1);
  if (!pathname.startsWith(base)) {
    return "/";
  }
  const route = pathname.slice(base.length) || "/";
  return route.startsWith("/") ? route : `/${route}`;
}

export function useInternalPath(runtime: ProfileRuntime): string {
  const [pathname, setPathname] = useState(() => internalPath(window.location.pathname, runtime));

  useEffect(() => {
    const update = () => setPathname(internalPath(window.location.pathname, runtime));
    window.addEventListener("popstate", update);
    return () => window.removeEventListener("popstate", update);
  }, [runtime]);

  return pathname;
}

export function AppLink({
  children,
  className,
  currentPath,
  runtime,
  to,
}: {
  children: ReactNode;
  className: string;
  currentPath: string;
  runtime: ProfileRuntime;
  to: string;
}) {
  const href = `${runtime.basePath.slice(0, -1)}${to === "/" ? "/" : to}`;
  const active = to === "/" ? currentPath === "/" : currentPath.startsWith(to);

  const navigate = (event: MouseEvent<HTMLAnchorElement>) => {
    if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) {
      return;
    }
    event.preventDefault();
    window.history.pushState({}, "", href);
    window.dispatchEvent(new PopStateEvent("popstate"));
  };

  return (
    <a
      aria-current={active ? "page" : undefined}
      className={`${className}${active ? " is-active" : ""}`}
      href={href}
      onClick={navigate}
    >
      {children}
    </a>
  );
}
