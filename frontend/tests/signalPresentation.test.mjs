import assert from "node:assert/strict"
import { readFile } from "node:fs/promises"
import test from "node:test"
import ts from "typescript"

const source = await readFile(new URL("../src/signalPresentation.ts", import.meta.url), "utf8")
const { outputText } = ts.transpileModule(source, { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext } })
const { displayValue, businessKeyLabel } = await import(`data:text/javascript;base64,${Buffer.from(outputText).toString("base64")}`)
const output = (value, unit_id = "ratio", status = "computed") => ({ value, unit_id, status })

test("formats the existing S1/S2/S3 ratios, with explicit display approximation", () => {
  assert.equal(displayValue(output("2.111902100000")), "≈211.19%")
  assert.equal(displayValue(output("-0.282948395517")), "≈-28.29%")
  assert.equal(displayValue(output("0.110198778230")), "≈11.02%")
})
test("keeps exact decimal and zero displays exact", () => {
  assert.equal(displayValue(output("0.4")), "40%")
  assert.equal(displayValue(output("0.1234")), "12.34%")
  assert.equal(displayValue(output("0")), "0%")
})
test("rounds carry without losing digits above the IEEE-754 safe range", () => {
  assert.equal(displayValue(output("0.999999")), "≈100%")
  assert.equal(displayValue(output("9007199254740993.001")), "900719925474099300.1%")
})
test("preserves raw money and never invents a value for undefined outputs", () => {
  assert.equal(displayValue(output("-1333369.720000000", "CNY")), "-1333369.720000000 CNY")
  assert.equal(displayValue(output(null, "ratio", "undefined")), "未定义")
  assert.equal(displayValue(output("1E-7")), "1E-7 ratio")
})
test("keeps ordered business key components", () => {
  assert.equal(businessKeyLabel({ components: [{ component_id: "region", normalized_value: "华北" }, { component_id: "product_id", normalized_value: 102 }] }), "region: 华北 · product_id: 102")
  assert.equal(businessKeyLabel(null), "整体范围")
})
