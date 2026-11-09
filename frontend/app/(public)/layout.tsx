import { FollowDeviceTheme } from "@/components/shell/FollowDeviceTheme";

// The pages for visitors: the home page and the sign-in pages. They are always set in Geist, the
// brand's typeface, whatever font the user picked for the app. With "Match device" (the default),
// they follow the device when it switches between light and dark.
export default function PublicLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="contents font-brand [font-size-adjust:none]">
      <FollowDeviceTheme />
      {children}
    </div>
  );
}
