<script setup lang="ts">
/**
 * AI 对话视图 — 流式思考 + 历史恢复
 *
 * 设计：
 * 1. 用户发送 → 立即出现「思考气泡」，逐阶段流式展示 thinkingSteps（NLU → Handler → LLM）
 *    每个阶段：step 名 + 实时计时 + spinner/checkmark 动画
 * 2. API 返回 → thinkingSteps 冻结（带真实耗时）+ 最终 reply 显示在下方
 * 3. onMounted → 加载历史 → 如有则恢复，无则显示欢迎
 */
import { nextTick, onMounted, ref, watch } from "vue";
import { api } from "@/core/rpc";

interface ThinkingStep {
  step: string;
  elapsed_ms?: number;
  detail?: string;
  status: "pending" | "running" | "done";
}

interface ChatMsg {
  id: number;
  role: "user" | "assistant" | "system";
  content: string;
  intent?: string;
  nluTier?: number;
  thinkingSteps?: ThinkingStep[];
  thinkingDone?: boolean;       // true = thinking 阶段结束，可以显示最终回复
  loading?: boolean;            // true = 整体还在处理（包括 LLM）
  ts: number;
}

const messages = ref<ChatMsg[]>([
  {
    id: 0,
    role: "assistant",
    content: "你好！我是股大师 AI 助手\n\n可以问我：持仓、行情、提醒、推荐",
    ts: Date.now(),
    thinkingDone: true,
  },
]);
const input = ref("");
const sending = ref(false);
const listEl = ref<HTMLElement | null>(null);
let nextId = 1;

// 模拟 thinking 的阶段定义（顺序固定 + 预估耗时）
// 前两步快速完成；最后一步「Ollama LLM 生成」保持 running 并实时计时，
// 直到 API 返回（由后端 thinking_steps 覆盖真实耗时），避免"思考已完成但无回复"的假象
const THINKING_PLAN: Array<{ step: string; duration_ms: number }> = [
  { step: "NLU 意图识别", duration_ms: 30 },
  { step: "Skill/Handler 执行", duration_ms: 80 },
  { step: "Ollama LLM 生成", duration_ms: 0 }, // 0 = 常驻 running，等待 API
];

/** 前端总等待上限（秒）：超过则给出友好提示，避免无限转圈（后端 45s 硬超时 + Rust 90s 兜底） */
const FRONT_TIMEOUT_SEC = 60;

async function scrollBottom() {
  await nextTick();
  if (listEl.value) {
    listEl.value.scrollTop = listEl.value.scrollHeight;
  }
}

/** 流式执行 thinking 阶段（前端模拟） */
function runThinkingSteps(
  loadingMsg: ChatMsg,
  onAllDone?: () => void
) {
  loadingMsg.thinkingSteps = THINKING_PLAN.map((p) => ({
    step: p.step,
    status: "pending" as const,
  }));
  loadingMsg.thinkingDone = false;

  let cumulative = 0;
  THINKING_PLAN.forEach((plan, idx) => {
    setTimeout(() => {
      // 标记当前阶段 running
      if (loadingMsg.thinkingSteps && loadingMsg.thinkingSteps[idx]) {
        loadingMsg.thinkingSteps[idx]!.status = "running";
      }

      // 阶段结束（留一点尾巴动画）
      // duration_ms === 0 表示常驻阶段（Ollama LLM 生成）：保持 running 直到 API 返回，
      // 由 send() 用后端 thinking_steps 覆盖为 done（或前端兜底超时强制结束）
      if (plan.duration_ms === 0) {
        return;
      }
      setTimeout(() => {
        if (loadingMsg.thinkingSteps && loadingMsg.thinkingSteps[idx]) {
          loadingMsg.thinkingSteps[idx]!.status = "done";
          loadingMsg.thinkingSteps[idx]!.elapsed_ms = Math.max(
            plan.duration_ms,
            10
          );
        }
        cumulative += plan.duration_ms;

        // 所有阶段完成
        if (idx === THINKING_PLAN.length - 1 && onAllDone) {
          onAllDone();
        }
      }, plan.duration_ms);
    }, idx === 0 ? 0 : cumulative);
  });
}

async function send() {
  const text = input.value.trim();
  if (!text || sending.value) return;

  messages.value.push({
    id: nextId++,
    role: "user",
    content: text,
    thinkingDone: true,
    ts: Date.now(),
  });
  input.value = "";
  sending.value = true;

  // AI 回复占位 — 带流式 thinking
  const loadingMsg: ChatMsg = {
    id: nextId++,
    role: "assistant",
    content: "正在思考...",
    loading: true,
    thinkingDone: false,
    ts: Date.now(),
  };
  messages.value.push(loadingMsg);
  scrollBottom();

  // 启动流式 thinking（不会等 API 返回 —— 视觉上先出现）
  runThinkingSteps(loadingMsg);

  // 前端兜底超时：后端/桥接异常时仍能结束 loading 态并给出提示
  let frontTimedOut = false;
  const frontTimer = setTimeout(() => {
    frontTimedOut = true;
    if (loadingMsg.thinkingDone) return;
    loadingMsg.content =
      "⏳ AI 响应较慢，已等待超过 " +
      FRONT_TIMEOUT_SEC +
      " 秒。本地模型推理需要一些时间，请稍后再试或换个问题。";
    if (loadingMsg.thinkingSteps) {
      loadingMsg.thinkingSteps.forEach((s) => {
        if (s.status === "running" || s.status === "pending") s.status = "done";
      });
    }
    loadingMsg.thinkingDone = true;
    loadingMsg.loading = false;
  }, FRONT_TIMEOUT_SEC * 1000);

  // 并行：调 API
  try {
    const resp: any = await api.executeSkill(text, Date.now());
    const result = resp?.result || resp;
    loadingMsg.content = result?.reply || "抱歉，我暂时没理解。";
    loadingMsg.intent = result?.intent;
    loadingMsg.nluTier = result?.nlu_tier;

    // 用后端真实耗时覆盖模拟值（如果有的话）
    const realSteps: Array<{ step: string; elapsed_ms: number }> =
      result?.thinking_steps || [];
    if (realSteps.length && loadingMsg.thinkingSteps) {
      realSteps.forEach((rs, i) => {
        if (loadingMsg.thinkingSteps![i]) {
          loadingMsg.thinkingSteps![i]!.elapsed_ms = rs.elapsed_ms;
          loadingMsg.thinkingSteps![i]!.status = "done";
        }
      });
    } else if (loadingMsg.thinkingSteps) {
      // 标记所有为 done
      loadingMsg.thinkingSteps.forEach((s) => {
        if (s.status === "pending") s.status = "done";
        if (!s.elapsed_ms) s.elapsed_ms = 10;
      });
    }

    loadingMsg.thinkingDone = true;
    loadingMsg.loading = false;
  } catch (e: any) {
    if (frontTimedOut) {
      // 兜底超时已给出提示，避免覆盖
    } else {
      loadingMsg.content = "请求失败：" + (e?.message || "未知错误");
      loadingMsg.thinkingDone = true;
      loadingMsg.loading = false;
    }
  } finally {
    clearTimeout(frontTimer);
    sending.value = false;
    scrollBottom();
  }
}

function onKeydown(e: KeyboardEvent) {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    send();
  }
}

function quickSend(q: string) {
  input.value = q;
  send();
}

watch(messages, () => scrollBottom(), { deep: true });

onMounted(async () => {
  scrollBottom();
  try {
    console.log("[ChatView] loading chat history...");
    const h: any = await api.chatHistoryList(50);
    console.log("[ChatView] history loaded:", h);
    if (h?.messages?.length) {
      const history: ChatMsg[] = h.messages.map((m: any) => ({
        id: Date.now() + Math.random(),
        role: m.role,
        content: m.content,
        intent: m.intent,
        ts: new Date(m.ts).getTime() || Date.now(),
        thinkingDone: true, // 历史消息视为已完成
      }));
      // 如果历史只有一个默认欢迎语（id=0），跳过，用新的
      const hasRealHistory = history.some(
        (m) =>
          m.role === "user" ||
          (m.content && !m.content.includes("你好！我是股大师"))
      );
      if (hasRealHistory) {
        messages.value = history;
      }
      await nextTick();
      scrollBottom();
      console.log("[ChatView] history applied, total:", messages.value.length);
    } else {
      console.log("[ChatView] no history messages");
    }
  } catch (e: any) {
    console.warn("[ChatView] history load failed:", e?.message || e);
    // 历史加载失败不阻塞界面，用默认欢迎语即可
  }
});
</script>

<template>
  <div class="chat-shell">
    <header class="chat-header">
      <span class="chat-title">AI 对话</span>
      <span class="chat-hint">Enter 发送 / Shift+Enter 换行</span>
    </header>

    <div ref="listEl" class="chat-list">
      <div
        v-for="m in messages"
        :key="m.id"
        class="msg-row"
        :class="[m.role, { loading: m.loading }]"
      >
        <div class="avatar">{{ m.role === "user" ? "U" : "AI" }}</div>
        <div class="bubble">
          <!-- 思考阶段（只有 AI 且有 thinkingSteps 才显示） -->
          <div
            v-if="m.thinkingSteps && m.thinkingSteps.length && !m.thinkingDone"
            class="thinking-block"
          >
            <div class="thinking-label">🧠 思考中...</div>
            <div class="thinking-flow">
              <div
                v-for="(s, idx) in m.thinkingSteps"
                :key="idx"
                class="tf-item"
                :class="{
                  done: s.status === 'done',
                  running: s.status === 'running',
                  pending: s.status === 'pending',
                }"
              >
                <span class="tf-icon">
                  <span v-if="s.status === 'pending'" class="tf-pending">○</span>
                  <span v-else-if="s.status === 'running'" class="tf-running">
                    <span class="spinner"></span>
                  </span>
                  <span v-else class="tf-check">✓</span>
                </span>
                <span class="tf-step">{{ s.step }}</span>
                <span v-if="s.status === 'done'" class="tf-ms">
                  {{ s.elapsed_ms }}ms
                </span>
              </div>
            </div>
          </div>

          <!-- 思考完成 → 分隔线 + 最终回复 -->
          <template v-if="m.thinkingDone">
            <div
              v-if="m.thinkingSteps && m.thinkingSteps.length"
              class="thinking-separator"
            ></div>
            <span class="bubble-text">{{ m.content }}</span>
          </template>

          <!-- 还在 thinking → 显示 loading 占位 -->
          <template v-else-if="m.loading">
            <span class="dots">
              <span></span><span></span><span></span>
            </span>
          </template>
        </div>
      </div>

      <div v-if="messages.length <= 1" class="quick-list">
        <button
          v-for="q in ['我赚了多少', '000001 多少钱', '设 3% 提醒', '推荐几只']"
          :key="q"
          class="quick-btn"
          @click="quickSend(q)"
        >
          {{ q }}
        </button>
      </div>
    </div>

    <footer class="chat-footer">
      <textarea
        v-model="input"
        class="chat-input"
        rows="1"
        placeholder="问我持仓、行情、提醒..."
        :disabled="sending"
        @keydown="onKeydown"
      ></textarea>
      <button
        class="send-btn"
        :class="{ disabled: !input.trim() || sending }"
        :disabled="!input.trim() || sending"
        @click="send"
      >
        {{ sending ? "..." : "发送" }}
      </button>
    </footer>
  </div>
</template>

<style scoped>
.chat-shell {
  width: 100%;
  height: 100%;
  box-sizing: border-box;
  background: var(--gd-bg-panel);
  backdrop-filter: blur(18px);
  border: 1px solid var(--gd-border);
  border-radius: var(--gd-radius);
  box-shadow: var(--gd-shadow);
  display: flex;
  flex-direction: column;
  overflow: hidden;
  font-size: 13px;
}

.chat-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 14px;
  border-bottom: 1px solid var(--gd-border);
  flex-shrink: 0;
}

.chat-title {
  font-weight: 600;
  color: var(--gd-primary);
}

.chat-hint {
  font-size: 10px;
  color: var(--gd-text-muted);
}

.chat-list {
  flex: 1;
  overflow-y: auto;
  min-height: 0;
  padding: 12px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.msg-row {
  display: flex;
  gap: 8px;
  max-width: 92%;
}

.msg-row.user {
  align-self: flex-end;
  flex-direction: row-reverse;
}

.msg-row.assistant {
  align-self: flex-start;
}

.avatar {
  width: 26px;
  height: 26px;
  border-radius: 50%;
  background: var(--gd-primary-soft);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 10px;
  font-weight: 700;
  color: var(--gd-primary);
  flex-shrink: 0;
}

.msg-row.user .avatar {
  background: rgba(255, 255, 255, 0.1);
  color: var(--gd-text);
}

.bubble {
  padding: 8px 12px;
  border-radius: 10px;
  line-height: 1.5;
  word-break: break-word;
  background: rgba(255, 255, 255, 0.06);
  border: 1px solid var(--gd-border);
  max-width: calc(100% - 40px);
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.msg-row.user .bubble {
  background: var(--gd-primary);
  border-color: var(--gd-primary);
  color: #0a0e17;
}

.msg-row.assistant .bubble {
  color: var(--gd-text);
}



.bubble-text {
  white-space: pre-wrap;
}

.dots {
  display: inline-flex;
  gap: 3px;
  padding: 2px 0;
}
.dots span {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--gd-text-muted);
  opacity: 0.6;
  animation: bounce 1.2s infinite ease-in-out;
}
.dots span:nth-child(2) { animation-delay: 0.15s; }
.dots span:nth-child(3) { animation-delay: 0.3s; }
@keyframes bounce {
  0%, 80%, 100% { transform: translateY(0); opacity: 0.4; }
  40% { transform: translateY(-4px); opacity: 1; }
}

.quick-list {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 4px;
}
.quick-btn {
  padding: 6px 10px;
  border: 1px solid var(--gd-border);
  border-radius: 14px;
  background: rgba(0, 212, 255, 0.08);
  color: var(--gd-primary);
  font-size: 11px;
  cursor: pointer;
  transition: background 0.15s;
}
.quick-btn:hover {
  background: rgba(0, 212, 255, 0.18);
}

.chat-footer {
  display: flex;
  gap: 8px;
  padding: 10px 12px;
  border-top: 1px solid var(--gd-border);
  flex-shrink: 0;
}
.chat-input {
  flex: 1;
  background: rgba(255, 255, 255, 0.05);
  border: 1px solid var(--gd-border);
  border-radius: 8px;
  padding: 8px 10px;
  color: var(--gd-text);
  font-size: 13px;
  font-family: inherit;
  resize: none;
  min-height: 36px;
  max-height: 80px;
  outline: none;
  line-height: 1.4;
}
.chat-input:focus { border-color: var(--gd-primary); }
.chat-input:disabled { opacity: 0.6; }
.send-btn {
  padding: 0 16px;
  height: 36px;
  background: var(--gd-primary);
  color: #fff;
  border: none;
  border-radius: 8px;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  flex-shrink: 0;
  transition: opacity 0.15s;
}
.send-btn.disabled, .send-btn:disabled {
  background: rgba(0, 212, 255, 0.3);
  cursor: not-allowed;
}

/* ====== 流式 Thinking 样式 ====== */
.thinking-block {
  background: rgba(0, 212, 255, 0.06);
  border: 1px solid rgba(0, 212, 255, 0.15);
  border-radius: 8px;
  padding: 8px 10px;
  margin-bottom: 4px;
  font-size: 11px;
}
.thinking-label {
  color: var(--gd-primary);
  font-weight: 600;
  margin-bottom: 6px;
  opacity: 0.9;
}
.thinking-flow {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.tf-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 2px 0;
  transition: all 0.2s;
}
.tf-item.done {
  color: var(--gd-text-muted);
  opacity: 0.7;
}
.tf-item.running {
  color: var(--gd-primary);
  font-weight: 500;
}
.tf-item.pending {
  color: var(--gd-text-muted);
  opacity: 0.4;
}
.tf-icon {
  width: 14px;
  text-align: center;
  font-size: 11px;
  flex-shrink: 0;
}
.tf-check {
  color: #4ade80;
}
.tf-pending {
  color: var(--gd-text-muted);
}
.tf-step {
  flex: 1;
}
.tf-ms {
  font-family: var(--gd-font-mono, monospace);
  font-size: 10px;
  color: var(--gd-primary);
  opacity: 0.8;
}

/* Spinner */
.spinner {
  display: inline-block;
  width: 11px;
  height: 11px;
  border: 2px solid rgba(0, 212, 255, 0.25);
  border-top-color: var(--gd-primary);
  border-radius: 50%;
  animation: spin 0.6s linear infinite;
}
@keyframes spin {
  to { transform: rotate(360deg); }
}

.thinking-separator {
  height: 1px;
  background: var(--gd-border);
  margin: 6px 0;
  opacity: 0.5;
}
</style>
