// Vitest setup: extend `expect` with DOM matchers (toBeInTheDocument, etc).
// Per the project rule "minimal abstractions", we don't add a global
// cleanup hook; React Testing Library's `cleanup` runs automatically
// in vitest when the test file imports `afterEach` from "vitest"
// and `cleanup` from "@testing-library/react" — see the test file.
import "@testing-library/jest-dom/vitest";
