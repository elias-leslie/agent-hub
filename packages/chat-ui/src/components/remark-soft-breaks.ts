/**
 * Remark plugin: a single newline inside text becomes a hard line break, so a
 * reply keeps the model's own lines (file lists, command output, step lines)
 * instead of CommonMark's soft-break collapse into one running line.
 *
 * Only `text` nodes are touched. Fenced and inline code are other node types
 * and keep their text; blank lines still split paragraphs before this runs.
 */
interface MdNode {
  type: string;
  value?: string;
  children?: MdNode[];
}

function splitSoftBreaks(node: MdNode): void {
  const children = node.children;
  if (!children) return;
  const next: MdNode[] = [];
  for (const child of children) {
    if (child.type === "text" && typeof child.value === "string" && child.value.includes("\n")) {
      child.value.split("\n").forEach((part, index) => {
        if (index > 0) next.push({ type: "break" });
        if (part) next.push({ type: "text", value: part });
      });
    } else {
      splitSoftBreaks(child);
      next.push(child);
    }
  }
  node.children = next;
}

export function remarkSoftBreaks() {
  return (tree: MdNode) => splitSoftBreaks(tree);
}
