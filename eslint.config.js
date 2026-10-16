import js from '@eslint/js'
import globals from 'globals'
import reactPlugin from 'eslint-plugin-react'
import reactHooks from 'eslint-plugin-react-hooks'
import tseslint from 'typescript-eslint'

// Vitest injects these into the global scope (`globals: true` in every SPA's
// vite.config test block). The `globals` package has no vitest set, so name them.
const TEST_GLOBALS = {
  describe: 'readonly',
  it: 'readonly',
  test: 'readonly',
  expect: 'readonly',
  vi: 'readonly',
  vitest: 'readonly',
  beforeAll: 'readonly',
  afterAll: 'readonly',
  beforeEach: 'readonly',
  afterEach: 'readonly',
}

export default [
  {
    // Build output, vendored code, and trees other seats own. `eslint .` from
    // the repo root would otherwise reach into the Python package and the
    // clients/ workspaces. The Desktop track lints `clients/desktop/**/*.ts`
    // via the appended block near the end of this file; everything else under
    // `clients/` stays out (the Rust/Tauri crate, the VR client).
    ignores: [
      '**/dist/**',
      '**/build/**',
      '**/coverage/**',
      '**/node_modules/**',
      // Workspace-local board/skill code and generated review/staging
      // artifacts are private tooling, not repository lint targets. A local
      // `eslint .` should match the clean-checkout CI surface.
      '.agents/**',
      '.artifacts/**',
      'docs/_private/**',
      // Local Python virtualenvs ship bundled JS (werkzeug debugger, urllib3
      // emscripten worker) that `eslint .` would otherwise lint. CI has no venv;
      // ignore it so `npm run lint` matches CI when run in a dev checkout.
      '**/venv/**',
      '**/.venv/**',
      '**/*.min.js',
      'oneirodex/**',
      'scripts/**',
      'clients/quest/**',
      'clients/desktop/src-tauri/**',
      // Standalone node harnesses for the classic (Jinja) theme JS. CI runs
      // them with `node` directly; they are not part of any SPA and predate
      // this seat's scope.
      'tests/**',
      // Generated — the source of truth is scripts/gen_loading_motifs.py.
      'frontend/member-app/src/components/systemMotifCatalogue.ts',
    ],
  },

  js.configs.recommended,

  // Member / admin / ops React SPAs, plus the shared frontend modules.
  {
    files: ['frontend/**/*.{js,jsx,mjs,cjs}'],
    languageOptions: {
      ecmaVersion: 2023,
      sourceType: 'module',
      parserOptions: { ecmaFeatures: { jsx: true } },
      globals: { ...globals.browser },
    },
    plugins: { react: reactPlugin, 'react-hooks': reactHooks },
    settings: { react: { version: 'detect' } },
    rules: {
      ...reactPlugin.configs.flat.recommended.rules,
      ...reactPlugin.configs.flat['jsx-runtime'].rules,
      // rules-of-hooks catches real bugs — keep it hard. exhaustive-deps is
      // advisory (Phase 3 tightens it). The rest of react-hooks v7's compiler
      // ruleset is deliberately not enabled here.
      'react-hooks/rules-of-hooks': 'error',
      'react-hooks/exhaustive-deps': 'warn',
      // The SPAs do not use PropTypes; TypeScript on-ramp (B0.3) is the type gate.
      'react/prop-types': 'off',
      // `_`-prefixed names are the codebase's "deliberately unused" marker
      // (e.g. `{ shellConfig: _shellConfig }`, `catch (_err)`).
      'no-unused-vars': [
        'warn',
        { argsIgnorePattern: '^_', varsIgnorePattern: '^_', caughtErrorsIgnorePattern: '^_' },
      ],
      'no-undef': 'error',
    },
  },

  // Frontend test, setup, and Vite config files run under Node with Vitest
  // globals in scope.
  {
    files: [
      'frontend/**/*.{test,spec}.{js,jsx}',
      'frontend/**/testSetup.{js,ts}',
      'frontend/**/vite.config.js',
      'frontend/**/*.config.{js,mjs}',
    ],
    languageOptions: { globals: { ...globals.node, ...TEST_GLOBALS } },
  },

  // TypeScript surface owned by this seat: the shared API client. Uses
  // typescript-eslint's non-type-checked recommended set (no project graph, so
  // it stays fast). The Tauri companion (also TS) is linted from the Desktop
  // track with this same block shape.
  ...tseslint.config({
    files: ['frontend/api-client/**/*.{ts,tsx}'],
    extends: [tseslint.configs.recommended],
    languageOptions: {
      globals: { ...globals.browser, ...globals.node },
    },
    rules: {
      '@typescript-eslint/no-unused-vars': 'warn',
      // Off on purpose: ~1,077 sites would drown the warnings that matter. The
      // gate is scripts/any_lint.mjs (per-file baseline, CI-run, only moves
      // down). Flip to 'error' when that baseline reaches 0.
      '@typescript-eslint/no-explicit-any': 'off',
      // tsc resolves identifiers and types; core no-undef only produces false
      // positives on a TS surface.
      'no-undef': 'off',
    },
  }),

  {
    files: ['frontend/api-client/**/*.{test,spec}.ts'],
    languageOptions: { globals: { ...TEST_GLOBALS } },
  },

  // TypeScript surface owned by this seat: `@oneirodex/ui` (frontend/shared),
  // ops-glance, and member-app (PR-5a). Same non-type-checked recommended set
  // as the api-client block above, plus the React plugins because these files
  // carry components/hooks.
  ...tseslint.config({
    files: [
      'frontend/shared/**/*.{ts,tsx}',
      'frontend/ops-glance/**/*.{ts,tsx}',
      'frontend/member-app/**/*.{ts,tsx}',
      'frontend/admin-app/**/*.{ts,tsx}',
    ],
    extends: [tseslint.configs.recommended],
    plugins: { react: reactPlugin, 'react-hooks': reactHooks },
    settings: { react: { version: 'detect' } },
    languageOptions: {
      globals: { ...globals.browser, ...globals.node },
    },
    rules: {
      ...reactPlugin.configs.flat.recommended.rules,
      ...reactPlugin.configs.flat['jsx-runtime'].rules,
      'react-hooks/rules-of-hooks': 'error',
      'react-hooks/exhaustive-deps': 'warn',
      'react/prop-types': 'off',
      '@typescript-eslint/no-unused-vars': [
        'warn',
        { argsIgnorePattern: '^_', varsIgnorePattern: '^_', caughtErrorsIgnorePattern: '^_' },
      ],
      // Off on purpose: ~1,077 sites would drown the warnings that matter. The
      // gate is scripts/any_lint.mjs (per-file baseline, CI-run, only moves
      // down). Flip to 'error' when that baseline reaches 0.
      '@typescript-eslint/no-explicit-any': 'off',
      'no-undef': 'off',
    },
  }),

  // --- Desktop track (clients/desktop) --------------------------------------
  // Appended by the Desktop seat (wave C3.7-client / ci-wishlist [B0.2]).
  // Mirrors the frontend/api-client block: typescript-eslint's non-type-checked
  // recommended set over the Tauri companion's TS. Same rule tweaks so the two
  // TS surfaces lint identically.
  ...tseslint.config({
    files: ['clients/desktop/**/*.{ts,tsx}'],
    extends: [tseslint.configs.recommended],
    languageOptions: {
      globals: { ...globals.browser, ...globals.node },
    },
    rules: {
      '@typescript-eslint/no-unused-vars': 'warn',
      // Off on purpose: ~1,077 sites would drown the warnings that matter. The
      // gate is scripts/any_lint.mjs (per-file baseline, CI-run, only moves
      // down). Flip to 'error' when that baseline reaches 0.
      '@typescript-eslint/no-explicit-any': 'off',
      'no-undef': 'off',
    },
  }),

  {
    files: ['clients/desktop/**/*.{test,spec}.ts'],
    languageOptions: { globals: { ...TEST_GLOBALS } },
  },

  // Repo-root tooling files (this config included).
  {
    files: ['*.js', '*.mjs'],
    languageOptions: { sourceType: 'module', globals: { ...globals.node } },
  },
]
