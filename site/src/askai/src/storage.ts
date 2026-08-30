// Thin localStorage wrapper: BYOK keys and small UI preferences never leave
// the browser (docs/PLAN.md §8), and reads/writes are wrapped in try/catch
// since localStorage can throw (private browsing, disabled storage) even
// though it's synchronously available in most browsers.

export function getItem(key: string): string | null {
  try {
    return window.localStorage.getItem(key);
  } catch {
    return null;
  }
}

export function setItem(key: string, value: string): void {
  try {
    window.localStorage.setItem(key, value);
  } catch {
    // Ignored — worst case, the preference/key just isn't remembered.
  }
}
