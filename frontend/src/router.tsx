import type { MouseEvent, ReactNode } from "react";
import { useEffect, useState } from "react";
import type { ProfileRuntime } from "./profile";

export function internalPath(pathname: string, runtime: ProfileRuntime): string {
  const base = runtime.basePath.slice(0, -1);
  if (!pathname.startsWith(base)) {
    return "/home";
  }
  const remainder = pathname.slice(base.length);
  const route = !remainder || remainder === "/" ? "/home" : remainder;
  return route.startsWith("/") ? route : `/${route}`;
}

export function currentInternalLocation(runtime: ProfileRuntime): string {
  return `${internalPath(window.location.pathname, runtime)}${window.location.search}${window.location.hash}`;
}

function safeInternalTarget(candidate: string | null): string {
  if (!candidate?.startsWith("/") || candidate.startsWith("//")) {
    return "/home";
  }
  return candidate;
}

export function safeReturnTo(candidate: string | null): string {
  const normalized = safeInternalTarget(candidate);
  const path = normalized.split(/[?#]/, 1)[0];
  return path === "/login" ? "/home" : normalized;
}

export function profileHref(runtime: ProfileRuntime, to: string): string {
  const normalized = safeInternalTarget(to);
  return `${runtime.basePath.slice(0, -1)}${normalized}`;
}

export function navigateInternal(runtime: ProfileRuntime, to: string, replace = false): void {
  const href = profileHref(runtime, to);
  if (replace) {
    window.history.replaceState({}, "", href);
  } else {
    window.history.pushState({}, "", href);
  }
  window.dispatchEvent(new PopStateEvent("popstate"));
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
  const href = profileHref(runtime, to);
  const active = currentPath === to || currentPath.startsWith(`${to}/`);

  const navigate = (event: MouseEvent<HTMLAnchorElement>) => {
    if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) {
      return;
    }
    event.preventDefault();
    navigateInternal(runtime, to);
    window.scrollTo({ behavior: "auto", left: 0, top: 0 });
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
