import { useEffect, useState } from "react";

type Theme = "light" | "dark";
const storageKey = "lora-lab-theme";

function savedTheme(): string | null {
  try {
    return localStorage.getItem(storageKey);
  } catch {
    return null;
  }
}

export function useTheme() {
  const [theme, setTheme] = useState<Theme>(() =>
    document.documentElement.dataset.theme === "dark" ? "dark" : "light",
  );

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    document
      .querySelector('meta[name="theme-color"]')
      ?.setAttribute("content", theme === "dark" ? "#101722" : "#f6f8fb");
  }, [theme]);

  useEffect(() => {
    const preference = matchMedia("(prefers-color-scheme: dark)");
    const followSystem = () => {
      const saved = savedTheme();
      if (saved !== "light" && saved !== "dark") {
        setTheme(preference.matches ? "dark" : "light");
      }
    };
    preference.addEventListener("change", followSystem);
    return () => preference.removeEventListener("change", followSystem);
  }, []);

  function toggleTheme() {
    const next = theme === "dark" ? "light" : "dark";
    try {
      localStorage.setItem(storageKey, next);
    } catch {
      // The toggle still works when browser storage is unavailable.
    }
    setTheme(next);
  }

  return { theme, toggleTheme };
}
