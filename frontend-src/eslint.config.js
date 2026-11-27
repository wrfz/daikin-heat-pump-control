import js from "@eslint/js";
import prettier from "eslint-config-prettier";
import lit from "eslint-plugin-lit";
import globals from "globals";
import tseslint from "typescript-eslint";

export default tseslint.config(
  { ignores: ["node_modules/", "layouts/"] },
  js.configs.recommended,
  ...tseslint.configs.strict,
  lit.configs["flat/recommended"],
  prettier,
  {
    languageOptions: { globals: { ...globals.browser } },
  },
  {
    // Tests know which elements exist.
    files: ["test/**/*.ts"],
    rules: { "@typescript-eslint/no-non-null-assertion": "off" },
  },
);
