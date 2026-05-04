/** Fix missing spaces in concatenated summaries (e.g. "opportunities.Good" → "opportunities. Good") */
export function fixSpacing(text: string): string {
  return text
    .replace(/([.!?])([A-Z])/g, '$1 $2') // period/excl/question + uppercase
    .replace(/(\])([A-Z])/g, '$1 $2') // closing bracket + uppercase
}
