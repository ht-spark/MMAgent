/** Render a stable document UUID compactly without changing its stored value. */
export function formatKnowledgeDocumentId(documentId: string): string {
  return documentId.length > 13
    ? `${documentId.slice(0, 8)}…${documentId.slice(-4)}`
    : documentId
}
