import "@testing-library/jest-dom/vitest";

// Mock scrollIntoView which doesn't exist in jsdom
Element.prototype.scrollIntoView = () => {};
