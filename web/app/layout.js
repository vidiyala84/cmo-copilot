import "./globals.css";
import Nav from "./components/Nav";

export const metadata = {
  title: "CMO Copilot — One Problem, Three Architectures",
  description: "Memory, Agent Society, and Autopilot on the same spend-reallocation harness.",
};

export default function RootLayout({ children }) {
  return (
    <html lang="en">
      <body>
        <div className="layout">
          <Nav />
          <main className="main">{children}</main>
        </div>
      </body>
    </html>
  );
}
