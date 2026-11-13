/**
 * 设置 store：皮肤偏好（B2）+ 产品配置（M2-2）
 *
 * 皮肤为宠物窗口本地视觉偏好，localStorage 持久化（同 origin 多窗口共享）。
 * 产品配置（刷新频率 / AI 开关 / 首启标记）经 config.get / config.set RPC
 * 后端持久化（user_config 表），热更新生效。
 */
import { defineStore } from "pinia";
import { reactive, ref, watch } from "vue";
import { api } from "@/core/rpc";

/** 可用皮肤清单（与 public/skins 目录一一对应） */
export const SKINS = [
  { id: "tech-bull", label: "机械金牛" },
  { id: "pixiu", label: "招财貔貅" },
  { id: "hamster", label: "理财仓鼠" },
] as const;

export type SkinId = (typeof SKINS)[number]["id"];

const SKIN_STORAGE_KEY = "gd.skin";
/** AI 开关跨窗口同步键（同 origin 多窗口共享：panel 设置页变更 → pet 实时感知） */
const AI_ENABLED_STORAGE_KEY = "gd.ai_enabled";

/** 皮肤状态图清单（与切图规范 v1.0 §2.2 对应） */
const SKIN_STATES = [
  "idle",
  "happy",
  "sad",
  "alert",
  "sleep",
  "blink",
  "drag", // 可选态：缺图回退 idle
  "press", // 可选态：缺图用 CSS scale 模拟
] as const;

/** 基础六态：占位素材已就位，乐观默认存在 */
const REQUIRED_STATE_COUNT = 6;

export const useSettingsStore = defineStore("settings", () => {
  // ---------- 皮肤 ----------
  const saved = localStorage.getItem(SKIN_STORAGE_KEY) as SkinId | null;
  const skin = ref<SkinId>(
    saved && SKINS.some((s) => s.id === saved) ? saved : SKINS[0].id,
  );

  watch(skin, (v) => localStorage.setItem(SKIN_STORAGE_KEY, v));

  // 跨窗口同步：panel 设置页改皮肤 → pet 窗口通过 storage 事件实时感知
  if (typeof window !== "undefined") {
    window.addEventListener("storage", (e: StorageEvent) => {
      if (e.key === SKIN_STORAGE_KEY && e.newValue) {
        const v = e.newValue as SkinId;
        if (SKINS.some((s) => s.id === v)) {
          skin.value = v;
        }
      }
    });
  }

  // ---------- 缺图探测：皮肤状态图存在性 ----------
  // 切图未交付时可选态（drag/press）自动降级，交付后无需改代码直接生效
  const assetOk = reactive<Record<string, boolean>>({});

  function probe(skinId: SkinId): void {
    for (let i = 0; i < SKIN_STATES.length; i++) {
      const st = SKIN_STATES[i];
      const key = `${skinId}/${st}`;
      if (key in assetOk) continue;
      // 基础态乐观（素材已就位），可选态悲观（探测成功才启用）
      assetOk[key] = i < REQUIRED_STATE_COUNT;
      const img = new Image();
      img.onload = () => (assetOk[key] = true);
      img.onerror = () => (assetOk[key] = false);
      img.src = `/skins/${skinId}/${st}.png`;
    }
  }

  /** 指定皮肤的某状态图是否可用 */
  function hasAsset(skinId: SkinId, state: string): boolean {
    return assetOk[`${skinId}/${state}`] === true;
  }

  /** 解析实际展示状态：缺图回退 idle（idle 为规范保证的必备态） */
  function resolveState(base: string, skinId: SkinId = skin.value): string {
    return hasAsset(skinId, base) ? base : "idle";
  }

  probe(skin.value);
  watch(skin, (v) => probe(v));

  // ---------- 产品配置（后端 user_config 持久化，M2-2） ----------
  /** 交易时段行情刷新间隔（秒）；后端 poll_loop 每轮读取，热生效 */
  const pollIntervalSec = ref(10);
  /** AI 对话能力开关（M2 门控；M3 接 Ollama 链路） */
  // 初始化优先取 localStorage（跨窗口共享的最近值），启动后 loadConfig 以后端为准覆盖
  const aiEnabled = ref(
    (() => {
      try {
        const v = localStorage.getItem(AI_ENABLED_STORAGE_KEY);
        return v ? JSON.parse(v) === true : false;
      } catch {
        return false;
      }
    })(),
  );
  /** 首启向导完成标记 */
  const firstRunDone = ref(true);
  /** 配置加载状态（首启向导需等加载完再判定是否展示） */
  const configLoaded = ref(false);

  // 跨窗口同步：panel 设置页改 AI 开关 → pet 窗口通过 storage 事件实时感知
  // （后端 config.set 保存后立即广播，避免 pet 侧 aiEnabled 陈旧导致聊天入口不出现）
  watch(aiEnabled, (v) =>
    localStorage.setItem(AI_ENABLED_STORAGE_KEY, JSON.stringify(v)),
  );
  if (typeof window !== "undefined") {
    window.addEventListener("storage", (e: StorageEvent) => {
      if (e.key === AI_ENABLED_STORAGE_KEY && e.newValue) {
        try {
          aiEnabled.value = JSON.parse(e.newValue) === true;
        } catch {
          /* 忽略非法值 */
        }
      }
    });
  }

  /** 从后端加载产品配置（App 初始化时调用） */
  async function loadConfig(): Promise<void> {
    try {
      const cfg = await api.getConfig();
      pollIntervalSec.value = Number(cfg.quote_polling_interval_cn) || 10;
      aiEnabled.value = cfg.ai_enabled === true || cfg.ai_enabled === "true";
      firstRunDone.value = cfg.first_run_done === true || cfg.first_run_done === "true";
    } catch {
      /* 后端不可达时保持默认值 */
    } finally {
      configLoaded.value = true;
    }
  }

  /** 写入单项配置（乐观更新，失败回滚由调用方处理） */
  async function setConfig(key: string, value: unknown): Promise<void> {
    await api.setConfig(key, value);
  }

  /** 设置刷新间隔（即时写后端，poll_loop 下一轮生效） */
  async function setPollInterval(sec: number): Promise<void> {
    const old = pollIntervalSec.value;
    pollIntervalSec.value = sec;
    try {
      await setConfig("quote_polling_interval_cn", sec);
    } catch {
      pollIntervalSec.value = old;
      throw new Error("保存失败");
    }
  }

  /** 切换 AI 对话开关（M2 仅切换 flag 与 UI 门控；Ollama 链路 M3） */
  async function setAiEnabled(on: boolean): Promise<void> {
    const old = aiEnabled.value;
    aiEnabled.value = on;
    try {
      await setConfig("ai_enabled", on);
    } catch {
      aiEnabled.value = old;
      throw new Error("保存失败");
    }
  }

  /** 标记首启向导完成 */
  async function markFirstRunDone(): Promise<void> {
    firstRunDone.value = true;
    try {
      await setConfig("first_run_done", true);
    } catch {
      /* 失败下次启动重新引导，无害 */
    }
  }

  return {
    skin,
    hasAsset,
    resolveState,
    pollIntervalSec,
    aiEnabled,
    firstRunDone,
    configLoaded,
    loadConfig,
    setPollInterval,
    setAiEnabled,
    markFirstRunDone,
  };
});
