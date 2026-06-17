import { defineConfig, globalIgnores } from "eslint/config";
import nextVitals from "eslint-config-next/core-web-vitals";
import nextTs from "eslint-config-next/typescript";

const eslintConfig = defineConfig([
  ...nextVitals,
  ...nextTs,
  // Override default ignores of eslint-config-next.
  globalIgnores([
    // Default ignores of eslint-config-next:
    ".next/**",
    "out/**",
    "build/**",
    "next-env.d.ts",
  ]),
  {
    // The React Compiler `react-hooks/refs` rule (eslint-plugin-react-hooks v6)
    // over-flags the DOCUMENTED-correct pattern of reading/writing a ref inside
    // event-handler callbacks (pointer-move resize, click-time scroll locks).
    // React explicitly endorses ref access in event handlers, so we downgrade
    // this experimental check to a warning rather than contort correct code.
    // Likewise `set-state-in-effect` fires on setState inside event listeners
    // registered from an effect (keydown handlers etc.) — also correct.
    rules: {
      "react-hooks/refs": "warn",
      "react-hooks/set-state-in-effect": "warn",
      // React Compiler "Existing memoization could not be preserved" is an
      // optimization hint (the auto-memoizer bails on a hand-written useMemo),
      // not a correctness error. Keep it visible as a warning.
      "react-hooks/preserve-manual-memoization": "warn",
    },
  },
]);

export default eslintConfig;
