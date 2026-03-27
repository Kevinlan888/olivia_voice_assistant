export const IS_IOS = /iPad|iPhone|iPod/.test(navigator.userAgent) ||
  (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1)

export function log(fmt, ...args) {
  const t = new Date().toISOString().slice(11, 23) // HH:MM:SS.mmm
  // vConsole doesn't expand %s/%d — interpolate manually
  let i = 0
  const msg = fmt.replace(/%[sd]/g, () => {
    const v = args[i++]
    return v === undefined ? '' : v
  })
  const rest = args.slice(i)
  console.log(`[Olivia ${t}] ${msg}`, ...rest)
}
