/**
 * Navigation icon registry.
 *
 * Navigation is server-driven, so icons arrive as strings. Resolving them with
 * `import * as icons from "lucide-react"` would pull the **entire** icon set
 * (~1,500 components, ~600 KB) into the entry chunk — so every icon the server
 * can name is imported explicitly here instead.
 *
 * Adding a navigation item on the backend means adding one line to this map.
 * An unknown name falls back to a neutral dot rather than crashing.
 */

import {
  Blocks,
  Building,
  Building2,
  Car,
  ChartColumn,
  Circle,
  CreditCard,
  DoorOpen,
  Droplets,
  LayoutDashboard,
  type LucideIcon,
  Megaphone,
  MessageSquareWarning,
  Package,
  Palette,
  PawPrint,
  ReceiptIndianRupee,
  ScrollText,
  Settings,
  ShieldCheck,
  Sparkles,
  SquareParking,
  Trees,
  UserCog,
  UserRoundCheck,
  Users,
  Wallet,
  Wrench,
  Zap,
} from "lucide-react";

const ICONS: Record<string, LucideIcon> = {
  Blocks,
  Building,
  Building2,
  Car,
  ChartColumn,
  Circle,
  CreditCard,
  DoorOpen,
  Droplets,
  LayoutDashboard,
  Megaphone,
  MessageSquareWarning,
  Package,
  Palette,
  PawPrint,
  ReceiptIndianRupee,
  ScrollText,
  Settings,
  ShieldCheck,
  Sparkles,
  SquareParking,
  Trees,
  UserCog,
  UserRoundCheck,
  Users,
  Wallet,
  Wrench,
  Zap,
};

export function NavIcon({ name, className }: { name: string; className?: string }) {
  const Icon = ICONS[name] ?? Circle;
  return <Icon className={className} aria-hidden />;
}
