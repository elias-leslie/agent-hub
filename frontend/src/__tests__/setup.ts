import '@testing-library/jest-dom/vitest'

// Mock scrollIntoView which doesn't exist in jsdom
if (typeof Element !== 'undefined') Element.prototype.scrollIntoView = () => {}
