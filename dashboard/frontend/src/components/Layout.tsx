import { NavLink, Outlet } from "react-router";

const NAV_ITEMS = [
  { to: "/",          label: "BRIDGE",    sub: "Main View"  },
  { to: "/projects",  label: "MISSIONS",  sub: "Projects"   },
  { to: "/prompts",   label: "CREW",      sub: "Personas"   },
  { to: "/schedules", label: "ORDERS",    sub: "Schedules"  },
  { to: "/costs",     label: "RESOURCES", sub: "Costs"      },
];

export default function Layout() {
  return (
    <div className="flex flex-col md:flex-row h-screen bg-lcars-bg font-lcars overflow-hidden">

      {/* ── Mobile top bar (visible below md) ── */}
      <div className="md:hidden h-10 bg-lcars-orange flex items-center px-4 shrink-0">
        <span className="text-black font-bold text-sm tracking-[0.2em] uppercase">
          BridgeCrew
        </span>
      </div>

      {/* ── LCARS Sidebar (hidden below md) ── */}
      <aside className="hidden md:flex w-52 flex-col shrink-0">

        {/* Top corner piece + title bar */}
        <div className="flex shrink-0" style={{ height: "72px" }}>
          {/* Rounded corner block */}
          <div className="w-12 h-full bg-lcars-orange rounded-br-[2rem] shrink-0" />
          {/* Title bar */}
          <div className="flex-1 flex flex-col justify-end pb-1 pl-3 bg-transparent">
            <div className="h-8 bg-lcars-orange flex items-center px-3 rounded-r-sm">
              <span className="text-black font-bold text-sm tracking-[0.2em] uppercase">
                BridgeCrew
              </span>
            </div>
          </div>
        </div>

        {/* Left accent bar + navigation */}
        <div className="flex flex-1 min-h-0">
          {/* Vertical LCARS bar with color segments */}
          <div className="w-12 flex flex-col shrink-0">
            <div className="h-1 bg-lcars-orange" />
            <div className="h-8 bg-lcars-blue" />
            <div className="h-1 bg-lcars-orange" />
            <div className="flex-1 bg-lcars-panel" />
            <div className="h-1 bg-lcars-orange" />
            <div className="h-8 bg-lcars-purple" />
            <div className="h-1 bg-lcars-orange" />
          </div>

          {/* Navigation */}
          <nav className="flex-1 flex flex-col justify-center gap-0.5 py-4 overflow-hidden">
            {NAV_ITEMS.map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                end={item.to === "/"}
                className={({ isActive }) =>
                  `group flex flex-col px-3 py-2 transition-all ${
                    isActive
                      ? "border-l-2 border-lcars-orange"
                      : "border-l-2 border-transparent hover:border-lcars-muted"
                  }`
                }
              >
                {({ isActive }) => (
                  <>
                    <span className={`text-xs font-bold tracking-[0.15em] ${
                      isActive ? "text-lcars-orange" : "text-lcars-muted group-hover:text-lcars-cyan"
                    }`}>
                      {item.label}
                    </span>
                    <span className={`text-xs ${
                      isActive ? "text-lcars-cyan" : "text-lcars-muted group-hover:text-lcars-text"
                    }`}>
                      {item.sub}
                    </span>
                  </>
                )}
              </NavLink>
            ))}
          </nav>
        </div>

        {/* Bottom corner piece */}
        <div className="flex shrink-0" style={{ height: "40px" }}>
          <div className="w-12 h-full bg-lcars-orange rounded-tr-[2rem] shrink-0" />
          <div className="flex-1 flex items-center pl-3">
            <span className="text-lcars-muted text-xs font-mono tracking-widest">
              LCARS v2.0
            </span>
          </div>
        </div>

      </aside>

      {/* ── Main content area ── */}
      <div className="flex-1 flex flex-col min-w-0 overflow-hidden">
        {/* Top accent line */}
        <div className="hidden md:block h-1 bg-gradient-to-r from-lcars-orange via-lcars-blue to-transparent shrink-0" />
        <main className="flex-1 overflow-auto p-3 md:p-6 pb-16 md:pb-6">
          <Outlet />
        </main>
      </div>

      {/* ── Mobile bottom tab bar (visible below md) ── */}
      <nav className="md:hidden fixed bottom-0 inset-x-0 h-14 bg-lcars-panel border-t border-lcars-border flex items-center justify-around z-50">
        {NAV_ITEMS.map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            end={item.to === "/"}
            className={({ isActive }) =>
              `flex flex-col items-center gap-0.5 px-2 py-1 ${
                isActive ? "text-lcars-orange" : "text-lcars-muted"
              }`
            }
          >
            <span className="text-[10px] font-bold tracking-[0.1em]">{item.label}</span>
          </NavLink>
        ))}
      </nav>

    </div>
  );
}
