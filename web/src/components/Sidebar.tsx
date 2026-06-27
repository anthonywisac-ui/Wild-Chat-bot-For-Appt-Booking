"use client";

import { usePathname, useRouter } from "next/navigation";
import {
  Sparkles,
  LayoutGrid,
  CalendarDays,
  Users,
  Stethoscope,
  Package,
  CreditCard,
  BarChart3,
  MessageCircle,
  Bell,
  ListChecks,
  Settings,
  ChevronRight,
} from "lucide-react";
import { clearToken } from "@/lib/api";

const mainNav = [
  { href: "/overview", label: "Overview", icon: LayoutGrid },
  { href: "/appointments", label: "Appointments", icon: CalendarDays },
  { href: "/patients", label: "Patients", icon: Users },
  { href: "/leads", label: "Leads", icon: Users, badge: true },
];

const clinicNav = [
  { href: "/doctors", label: "Doctors", icon: Stethoscope },
  { href: "/treatments", label: "Treatments", icon: ListChecks },
  { href: "/packages", label: "Packages", icon: Package },
  { href: "/payments", label: "Payments", icon: CreditCard },
  { href: "/reports", label: "Reports", icon: BarChart3 },
];

const systemNav = [
  { href: "/channels", label: "Channels", icon: MessageCircle },
  { href: "/reminders", label: "Reminders", icon: Bell },
  { href: "/bot-settings", label: "Bot settings", icon: Settings },
];

function NavGroup({
  title,
  items,
  pathname,
  router,
  badgeValue,
}: {
  title: string;
  items: typeof mainNav;
  pathname: string;
  router: ReturnType<typeof useRouter>;
  badgeValue?: number;
}) {
  return (
    <div className="mb-1">
      <p className="text-[10.5px] font-bold text-ink-faint tracking-wide px-2 mb-2">
        {title}
      </p>
      {items.map((item) => {
        const active = pathname === item.href;
        const Icon = item.icon;
        return (
          <button
            key={item.href}
            onClick={() => router.push(item.href)}
            className={`w-full flex items-center gap-2.5 px-3 py-2.5 rounded-xl text-sm mb-0.5 transition-colors text-left ${
              active
                ? "bg-primary-soft text-primary-dark font-semibold"
                : "text-ink-muted hover:bg-bg font-medium"
            }`}
          >
            <Icon size={16} strokeWidth={2} />
            <span className="flex-1">{item.label}</span>
            {item.badge && badgeValue ? (
              <span className="bg-ink text-white text-[10px] font-bold px-1.5 py-0.5 rounded-md">
                {badgeValue}
              </span>
            ) : null}
          </button>
        );
      })}
    </div>
  );
}

export function Sidebar({
  username,
  leadCount,
}: {
  username: string;
  leadCount?: number;
}) {
  const pathname = usePathname();
  const router = useRouter();

  function handleLogout() {
    clearToken();
    router.push("/");
  }

  return (
    <aside className="w-[224px] shrink-0 bg-card border-r border-border px-3.5 py-5 flex flex-col">
      <div className="flex items-center gap-2 px-2 mb-7">
        <div className="w-7 h-7 rounded-lg bg-primary flex items-center justify-center">
          <Sparkles size={14} className="text-white" />
        </div>
        <span className="text-[15px] font-extrabold tracking-tight">
          Wild Aesthetics
        </span>
      </div>

      <NavGroup title="MAIN" items={mainNav} pathname={pathname} router={router} badgeValue={leadCount} />
      <div className="h-3" />
      <NavGroup title="CLINIC" items={clinicNav} pathname={pathname} router={router} />
      <div className="h-3" />
      <NavGroup title="SYSTEM" items={systemNav} pathname={pathname} router={router} />

      <div className="mt-auto pt-3 border-t border-border flex items-center gap-2 px-2">
        <div className="w-8 h-8 rounded-full bg-primary-soft flex items-center justify-center text-xs font-bold text-primary-dark shrink-0">
          {username.slice(0, 2).toUpperCase()}
        </div>
        <div className="flex-1 min-w-0">
          <p className="text-xs font-semibold truncate">{username}</p>
          <p className="text-[10.5px] text-ink-faint">Owner</p>
        </div>
        <button
          onClick={handleLogout}
          className="text-ink-faint hover:text-ink transition-colors"
          aria-label="Log out"
        >
          <ChevronRight size={14} />
        </button>
      </div>
    </aside>
  );
}
