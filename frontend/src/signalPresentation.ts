import type { BusinessKey, ComputationResult, FormulaId } from "./types"

export const formulaLabels: Record<FormulaId, string> = {
  attainment_rate: "目标完成率",
  absolute_change: "销售额变化",
  change_rate: "销售变化率",
  contribution_rate: "产品贡献率",
}

export function businessKeyLabel(key: BusinessKey | null): string {
  return key?.components.map(part => `${part.component_id}: ${part.normalized_value}`).join(" · ") || "整体范围"
}

export function displayValue(output: ComputationResult): string {
  if (output.status !== "computed" || output.value === null) return "未定义"
  if (output.unit_id !== "ratio") return `${output.value} ${output.unit_id ?? ""}`.trim()
  // Shift the supplied decimal string for percent presentation, without
  // converting exact contract values to IEEE-754 or recalculating a Signal.
  const match = /^(-?)(\d+)(?:\.(\d+))?$/.exec(output.value)
  if (!match) return `${output.value} ratio`
  const fraction = (match[3] ?? "").padEnd(2, "0")
  const whole = `${match[2]}${fraction.slice(0, 2)}`.replace(/^0+(?=\d)/, "")
  const tail = fraction.slice(2)
  const approximate = /[1-9]/.test(tail.slice(2))
  // Round only the display to two percentage decimals, including carry,
  // while retaining the original value next to it in the card.
  let hundredths = BigInt(whole) * 100n + BigInt(tail.slice(0, 2).padEnd(2, "0"))
  if ((tail[2] ?? "0") >= "5") hundredths += 1n
  const digits = hundredths.toString().padStart(3, "0")
  const decimals = digits.slice(-2).replace(/0+$/, "")
  return `${approximate ? "≈" : ""}${match[1]}${digits.slice(0, -2)}${decimals ? `.${decimals}` : ""}%`
}
