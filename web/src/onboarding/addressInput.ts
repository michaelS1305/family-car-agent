// Server resolves the full input and requires confirmation of the resulting proposal.
export function isValidAddress(address: string): boolean {
  return address.trim().length > 0 && [...address].length <= 200
}
