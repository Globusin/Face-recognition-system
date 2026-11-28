export const STATE_LABELS = {
  IDLE: 'Ожидание',
  TRACKING: 'Лицо в кадре',
  EVALUATING: 'Проверка',
  CHALLENGE: 'Выполнение задания',
  GRANTED: 'Доступ разрешён',
  DENIED: 'Отказ',
  COOLDOWN: 'Завершение попытки',
  ERROR: 'Ошибка оборудования',
};

export const CHECK_LABELS = {
  recognition: 'Распознавание',
  stereo: 'Объём лица',
  challenge: 'Задание',
};

export const STATUS_LABELS = {
  PASS: 'пройдено',
  FAIL: 'отказ',
  NOT_AVAILABLE: 'нет данных',
  SKIPPED: 'не требуется',
};

export const REASON_LABELS = {
  identity_not_confirmed: 'Лицо не распознано',
  identity_confirmed: 'Личность подтверждена',
  liveness_spoof: 'Обнаружена подделка',
  stereo_required: 'Нет обязательной проверки объёма',
  stereo_not_passed: 'Проверка объёма не пройдена',
  stereo_not_ready: 'Нет данных об объёме лица',
  challenge_passed: 'Задание выполнено',
  challenge_failed: 'Задание не выполнено',
  challenge_not_passed: 'Задание не выполнено',
  challenge_required: 'Требуется задание',
  challenge_reused: 'Результат задания нельзя переиспользовать',
  identity_changed: 'Перед камерой другой человек',
  identity_not_measured: 'Личность после задания не подтверждена',
  timeout: 'Время ожидания истекло',
  face_lost: 'Лицо потеряно',
  multiple_faces: 'В кадре несколько лиц',
  track_changed: 'Сменился человек в кадре',
  stale_frame: 'Кадры устарели',
  display_error: 'Ошибка дисплея',
  display_unavailable: 'Дисплей недоступен',
  camera_unavailable: 'Камера недоступна',
  processing_error: 'Ошибка обработки',
  unlock_failed: 'Ошибка открытия замка',
  lock_failed: 'Ошибка закрытия замка',
  policy_config_error: 'Ошибка настроек политики',
  challenge_config_error: 'Ошибка настроек заданий',
};

export const COMMAND_LABELS = {
  TURN_LEFT: 'Поверните голову влево',
  TURN_RIGHT: 'Поверните голову вправо',
  BLINK: 'Моргните двумя глазами',
};

export const CHALLENGE_STAGE_LABELS = {
  baseline: 'исходное положение',
  prompt: 'команда',
  action: 'выполнение',
  return: 'возврат в исходное положение',
  passed: 'выполнено',
  failed: 'не выполнено',
};

export const STEREO_DECISION_LABELS = {
  LIVE: 'объёмное лицо',
  SPOOF: 'признаки подделки',
  UNKNOWN: 'не определено',
};

export function stateLabel(value) {
  return STATE_LABELS[value] || value || '—';
}

export function statusLabel(value) {
  return STATUS_LABELS[value] || '—';
}

export function reasonLabel(value) {
  return REASON_LABELS[value] || value || '—';
}

export function decisionLabel(value) {
  if (value === 'GRANTED') return 'Допуск';
  if (value === 'DENIED') return 'Отказ';
  if (value === 'PENDING') return 'В процессе';
  return '—';
}

export function decisionColor(value) {
  if (value === 'GRANTED') return 'success';
  if (value === 'DENIED') return 'error';
  if (value === 'PENDING') return 'info';
  return 'grey';
}

export function statusColor(value) {
  if (value === 'PASS') return 'success';
  if (value === 'FAIL') return 'error';
  if (value === 'NOT_AVAILABLE') return 'warning';
  return 'grey';
}
