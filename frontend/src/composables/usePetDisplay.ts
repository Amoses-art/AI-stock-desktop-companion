/**
 * 宠物渲染状态与帧动画调度（M2-1 从 PetView 拆出）
 *
 * 展示状态优先级：拖拽 > 按压 > 眨眼 > 情绪；缺图回退 idle。
 * 帧动画（sprite sheet，切图 v1-rev1）仅基于 tech-bull 交付，
 * 其他皮肤自动降级为静态状态图。
 */
import { computed, ref, type Ref } from "vue";
import { usePetStore } from "@/stores/pet";
import { useSettingsStore, type SkinId } from "@/stores/settings";

/** 切图 v1-rev1：帧动画当前仅基于 tech-bull 交付 */
const ANIM_SKINS: readonly SkinId[] = ["tech-bull"];

/** 入场动画时长（8 帧 × 100ms） */
export const ENTER_MS = 800;

export function usePetDisplay(dragging: Ref<boolean>, pressing: Ref<boolean>) {
  const pet = usePetStore();
  const settings = useSettingsStore();

  const hasSkinAnims = computed(() => ANIM_SKINS.includes(settings.skin));

  /** 入场动画播放一次后进入正常状态机渲染 */
  const entering = ref(true);
  const enterDone = (): void => {
    entering.value = false;
  };

  /** 展示状态优先级：拖拽 > 按压 > 眨眼 > 情绪；缺图回退 idle */
  const displayState = computed(() => {
    if (dragging.value) return settings.resolveState("drag");
    if (pet.blinking) return settings.resolveState("blink");
    if (pressing.value && settings.resolveState("press") === "press") {
      return "press";
    }
    return settings.resolveState(pet.state);
  });

  const imgSrc = computed(
    () => `/skins/${settings.skin}/${displayState.value}.png`,
  );

  /** press.png 缺失时用 CSS scale 模拟按压（切图规范 §2.2 可选项） */
  const pressSimulated = computed(
    () =>
      pressing.value && !dragging.value && settings.resolveState("press") !== "press",
  );

  /** 统一 inline 样式：按压模拟（inline 优先级稳定压过 hover 的 scale 放大） */
  const petStyle = computed(() => ({
    filter: pressSimulated.value ? "brightness(0.92)" : undefined,
    transform: pressSimulated.value ? "scale(0.95)" : undefined,
  }));

  /** alert 循环动画激活条件 */
  const alertAnimating = computed(
    () =>
      hasSkinAnims.value &&
      pet.state === "alert" &&
      !dragging.value &&
      !pressing.value,
  );

  /** 眨眼动画激活条件（与 pet store 的 blink 时长联动） */
  const blinkAnimating = computed(
    () => hasSkinAnims.value && pet.blinking && !dragging.value && !pressing.value,
  );

  return {
    entering,
    enterDone,
    displayState,
    imgSrc,
    petStyle,
    alertAnimating,
    blinkAnimating,
  };
}
