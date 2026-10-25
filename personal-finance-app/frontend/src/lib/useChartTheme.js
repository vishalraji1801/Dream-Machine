import { useEffect, useState } from 'react';

const TOKENS = ['s1', 's2', 's3', 'ink', 'ink-2', 'muted', 'grid', 'hair', 'surface', 'critical'];

// Recharts needs literal colors: var() is invalid inside SVG presentation attributes.
function readTokens() {
  const styles = getComputedStyle(document.documentElement);
  return Object.fromEntries(
    TOKENS.map((t) => [t, styles.getPropertyValue(`--color-${t}`).trim() || '#888888']),
  );
}

export function useChartTheme(themeKey) {
  const [colors, setColors] = useState(readTokens);

  useEffect(() => {
    // Wait a frame so the attribute swap has been applied before sampling.
    const id = requestAnimationFrame(() => setColors(readTokens()));
    return () => cancelAnimationFrame(id);
  }, [themeKey]);

  useEffect(() => {
    const mq = window.matchMedia('(prefers-color-scheme: dark)');
    const onChange = () => setColors(readTokens());
    mq.addEventListener('change', onChange);
    return () => mq.removeEventListener('change', onChange);
  }, []);

  return colors;
}
