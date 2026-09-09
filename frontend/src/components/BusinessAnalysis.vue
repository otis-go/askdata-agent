<script setup lang="ts">
import { computed, ref } from "vue"
import type { BusinessSignalSummary, ExplanationResponse } from "../types"
import { businessKeyLabel, displayValue, formulaLabels } from "../signalPresentation"

const props = defineProps<{
  signals?: BusinessSignalSummary[]
  explanation?: ExplanationResponse | null
}>()

const titles = {
  monthly_regional_target_attainment: "S1 · 目标完成率",
  regional_sales_change: "S2 · 销售变化",
  product_contribution: "S3 · 产品贡献",
}
const available = computed(() => props.explanation?.generation_status === "generated" && Boolean(props.explanation.text))
const expanded = ref(false)
const visibleSignals = computed(() => expanded.value ? props.signals : props.signals?.slice(0, 4))
const unavailableReason = computed(() => {
  switch (props.explanation?.generation_status) {
    case "failed": return "解释服务本次生成失败。"
    case "validation_failed": return "解释未通过校验。"
    case "not_requested": return "本次没有可用于解释的业务信号。"
    default: return "本次没有可用的业务解释。"
  }
})
</script>

<template>
  <section class="business-analysis" aria-label="业务分析">
    <header class="analysis-heading">
      <strong>业务分析</strong>
      <small>Business Signals · {{ signals?.length ?? 0 }} 条</small>
    </header>
    <div v-if="signals?.length" class="signal-grid">
      <article v-for="signal in visibleSignals" :key="signal.signal_index" class="signal-card" data-testid="business-signal">
        <header><strong>{{ titles[signal.signal_type] }}</strong><span class="signal-status">{{ signal.status }}</span></header>
        <small class="signal-type">{{ signal.signal_type }}</small>
        <p class="signal-key"><small>business_key</small>{{ businessKeyLabel(signal.business_key) }}</p>
        <div v-for="output in signal.computed_value" :key="output?.formula_id" class="signal-output" :class="{ secondary: output?.formula_id === 'absolute_change' }">
          <template v-if="output">
            <span>{{ formulaLabels[output.formula_id] }}</span>
            <strong>{{ displayValue(output) }}</strong>
            <small>computed_value · {{ output.formula_id }}: {{ output.value ?? 'null' }}<template v-if="output.unit_id"> ({{ output.unit_id }})</template></small>
            <small v-if="output.numeric_quality.source_fidelity === 'approximate'">来源数值为近似值</small>
            <small v-if="output.status !== 'computed'">{{ output.status }} · {{ output.reason_code }}</small>
          </template>
        </div>
        <details class="signal-evidence">
          <summary>Evidence 摘要 · {{ signal.evidence_summary.length }} 个 operand</summary>
          <div v-for="evidence in signal.evidence_summary" :key="evidence.evidence_id" class="evidence-operand">
            <strong>{{ evidence.context_role }}</strong>
            <dl>
              <dt>formula</dt><dd>{{ evidence.formula_refs.map(item => `${item.formula_id} v${item.formula_version}`).join(' · ') }}</dd>
              <dt>operand 来源</dt><dd>{{ evidence.source_fields?.map(item => [item.database, item.table, item.field].filter(Boolean).join('.')).join(' · ') || '来源未提供' }}<template v-if="evidence.column_id"> · {{ evidence.column_id }}</template><template v-if="evidence.row_index !== null"> · row {{ evidence.row_index }}</template></dd>
              <dt>result_id</dt><dd>{{ evidence.result_id }}</dd>
              <dt>business key</dt><dd>{{ businessKeyLabel(evidence.business_key) }}</dd>
            </dl>
          </div>
        </details>
      </article>
    </div>
    <p v-else class="no-signals">暂无可展示的 Business Signal。</p>
    <button v-if="(signals?.length ?? 0) > 4" class="more-signals" :aria-expanded="expanded" @click="expanded = !expanded">
      {{ expanded ? '收起信号' : `展开其余 ${(signals?.length ?? 0) - 4} 条信号` }}
    </button>

    <section class="business-explanation" aria-label="业务解释" data-testid="business-explanation">
      <header><strong>解释</strong><small>{{ explanation?.generation_status ?? 'unavailable' }}</small></header>
      <p v-if="available" class="explanation-text">{{ explanation?.text }}</p>
      <div v-else class="explanation-unavailable" role="status">
        <strong>解释不可用</strong>
        <p>{{ unavailableReason }}SQL 查询结果仍可查看。</p>
      </div>
    </section>
  </section>
</template>

<style scoped>
.business-analysis { margin-top: 22px; padding-top: 18px; border-top: 1px solid var(--line); }
.analysis-heading, .signal-card > header, .business-explanation > header { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
.analysis-heading { margin-bottom: 12px; }
.analysis-heading > strong, .business-explanation > header strong { font-size: 14px; }
.analysis-heading small, .business-explanation > header small { color: var(--muted); font-size: 11px; }
.signal-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 200px), 1fr)); gap: 10px; }
.signal-card { min-width: 0; padding: 15px; border: 1px solid #dce8df; border-radius: 10px; background: #fff; }
.signal-card > header strong { font-size: 12px; }
.signal-status { padding: 3px 7px; border-radius: 5px; color: #276548; background: #eef5ef; font-size: 10px; }
.signal-type { display: block; margin-top: 5px; color: var(--muted); font-size: 10px; overflow-wrap: anywhere; }
.signal-key { margin: 13px 0 10px; font-size: 12px; overflow-wrap: anywhere; }
.signal-key small { display: block; margin-bottom: 3px; color: var(--muted); font-size: 10px; }
.signal-output { display: grid; gap: 4px; margin-top: 9px; }
.signal-output > span { font-size: 11px; color: #59665e; }
.signal-output > strong { color: var(--green); font-size: 25px; line-height: 1.2; overflow-wrap: anywhere; }
.signal-output.secondary > strong { font-size: 16px; }
.signal-output > small { color: #718077; font-size: 10px; overflow-wrap: anywhere; }
.signal-evidence { margin-top: 14px; padding-top: 10px; border-top: 1px solid var(--line); font-size: 10px; }
.signal-evidence summary { cursor: pointer; color: #586c5e; }
.evidence-operand { margin-top: 12px; }
.evidence-operand > strong { color: #3b5745; }
.evidence-operand dl { display: grid; gap: 3px; margin: 7px 0 0; }
.evidence-operand dt { color: #718077; }
.evidence-operand dd { margin: 0 0 5px; overflow-wrap: anywhere; line-height: 1.5; }
.business-explanation { margin-top: 17px; padding: 15px; border-radius: 8px; background: #f0f5f0; }
.explanation-text { margin: 12px 0 0; white-space: pre-wrap; overflow-wrap: anywhere; color: #3d4942; font-size: 12px; line-height: 1.85; }
.explanation-unavailable { margin-top: 12px; color: #746249; font-size: 12px; }
.explanation-unavailable p { margin: 5px 0 0; color: #69756c; line-height: 1.7; }
.no-signals { color: var(--muted); font-size: 12px; }
.more-signals { margin-top: 10px; padding: 7px 11px; border: 1px solid var(--line); border-radius: 6px; background: white; color: var(--green); font-size: 11px; }
</style>
