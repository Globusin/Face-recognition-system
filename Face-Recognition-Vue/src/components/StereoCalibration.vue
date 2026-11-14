<template>
    <section class="calibration d-flex flex-column ga-4">
        <div class="d-flex align-center justify-space-between flex-wrap ga-3">
            <div>
                <h2 class="text-h5">Калибровка стереопары</h2>
                <p class="text-body-2 mt-2">Настройка двух камер по шахматной доске и проверка точности глубины.</p>
            </div>
            <div class="d-flex align-center ga-2 flex-wrap">
                <v-chip :color="state.active ? 'warning' : 'grey'">
                    {{ state.active ? 'Сессия активна · распознавание приостановлено' : 'Сессия не запущена' }}
                </v-chip>
                <v-btn v-if="authorized" icon="mdi-refresh" variant="text" title="Обновить состояние"
                    :disabled="busy" @click="connect" />
            </div>
        </div>

        <v-alert v-if="error" type="error" variant="tonal" closable @click:close="error = ''">
            {{ error }}
        </v-alert>

        <v-card v-if="!authorized" variant="outlined">
            <v-card-title>Доступ администратора</v-card-title>
            <v-card-text class="d-flex flex-column ga-3">
                <p class="text-body-2">Введите токен администратора, чтобы получить состояние камер и управлять калибровкой.</p>
                <v-form class="d-flex align-start flex-wrap ga-3" @submit.prevent="connect">
                    <v-text-field v-model="token" type="password" label="Токен администратора"
                        autocomplete="off" variant="outlined" hide-details :disabled="busy" />
                    <v-btn type="submit" prepend-icon="mdi-login" :loading="busy">Подключиться</v-btn>
                </v-form>
            </v-card-text>
        </v-card>

        <template v-if="authorized">
            <div class="d-flex align-center flex-wrap ga-2">
                <v-chip variant="outlined">Шахматная доска · 7 × 7 внутренних углов</v-chip>
                <v-chip variant="outlined">Клетка · {{ state.active ? state.square_mm : squareMm }} мм</v-chip>
                <v-chip variant="outlined">Расстояние между камерами · 120 мм</v-chip>
            </div>

            <v-card v-if="!state.active" variant="outlined">
                <v-card-title>1. Подготовьте камеры и доску</v-card-title>
                <v-card-text class="d-flex flex-column ga-3">
                    <p class="text-body-2">Жёстко закрепите обе камеры, настройте фокус и измерьте сторону одной клетки шахматной доски. Во время всей сессии не меняйте положение камер друг относительно друга.</p>
                    <v-text-field v-model.number="squareMm" type="number" min="0.1" step="0.1"
                        label="Размер клетки доски, мм" variant="outlined" hide-details :disabled="busy" />
                    <v-checkbox v-model="mountingConfirmed" hide-details :disabled="busy"
                        label="Камеры закреплены, фокус и размер клетки проверены" />
                    <div class="d-flex align-center flex-wrap ga-3">
                        <v-btn prepend-icon="mdi-camera-control" :loading="busy"
                            :disabled="!mountingConfirmed || !validSquare" @click="start">
                            Начать калибровку
                        </v-btn>
                        <span class="text-body-2">На следующем этапе потребуется минимум 15 обучающих и 3 контрольные пары.</span>
                    </div>
                </v-card-text>
            </v-card>

            <template v-if="state.active">
                <v-card variant="outlined">
                    <v-card-title>1. Соберите пары кадров</v-card-title>
                    <v-card-text class="d-flex flex-column ga-4">
                        <div class="d-flex align-center flex-wrap ga-3">
                            <v-chip :color="state.training_pairs >= 15 ? 'success' : 'warning'">
                                Обучающие: {{ state.training_pairs }} / 15
                            </v-chip>
                            <v-chip :color="state.validation_pairs >= 3 ? 'success' : 'warning'">
                                Контрольные: {{ state.validation_pairs }} / 3
                            </v-chip>
                        </div>
                        <v-alert v-if="state.training_pairs >= 15 && state.validation_pairs >= 3"
                            type="success" variant="tonal">
                            Нужное количество кадров собрано. Можно перейти к расчёту ниже.
                        </v-alert>
                        <p v-else class="text-body-2">
                            Поместите доску так, чтобы её было полностью видно на обеих камерах. После каждого сохранения
                            изменяйте положение или наклон доски. Сначала соберите обучающие пары, затем контрольные.
                        </p>

                        <div class="d-flex align-start flex-wrap ga-3">
                            <v-select v-model="rotation" :items="rotations" item-title="title" item-value="value"
                                label="Поворот порядка углов второй камеры" variant="outlined" hide-details
                                :disabled="busy" style="min-width: 240px; flex: 1" @update:model-value="clearObservation" />
                            <v-btn prepend-icon="mdi-camera-refresh" :loading="busy" @click="observe">
                                Получить пару кадров
                            </v-btn>
                        </div>
                        <span class="text-body-2">Поворот углов обычно равен 0°. Изменяйте его только если нумерация углов не совпадает на двух изображениях.</span>

                        <div class="calibration-images">
                            <div v-for="role in roles" :key="role" style="min-width: 0">
                                <div class="d-flex align-center justify-space-between flex-wrap ga-2 mb-2">
                                    <strong>{{ role === 'primary' ? 'Основная камера' : 'Дополнительная камера' }}</strong>
                                    <v-chip size="small" :color="observation?.found[role] ? 'success' : 'grey'">
                                        {{ !observation ? 'Ожидание кадра' : observation.found[role] ? 'Найдено 49 углов' : 'Доска не найдена' }}
                                    </v-chip>
                                </div>
                                <div class="calibration-image">
                                    <img v-if="observation?.previews[role]" :src="observation.previews[role]"
                                        :alt="role === 'primary' ? 'Кадр основной камеры' : 'Кадр дополнительной камеры'">
                                    <v-icon v-else icon="mdi-chess-board" size="48" color="grey" />
                                </div>
                                <v-btn class="mt-2" prepend-icon="mdi-download" variant="outlined"
                                    :disabled="!observation || busy" @click="downloadFrame(role)">
                                    Скачать исходный кадр
                                </v-btn>
                            </div>
                        </div>
                        <v-alert v-if="observation && !pairReady" type="warning" variant="tonal">
                            Доска должна определяться на обоих кадрах. Измените её положение или освещение и получите новую пару.
                        </v-alert>
                        <div class="d-flex align-center flex-wrap ga-3">
                            <v-chip v-if="observation" variant="outlined">
                                Разница получения кадров: {{ observation.delta_ms.toFixed(1) }} мс
                            </v-chip>
                            <v-checkbox v-model="orientationConfirmed" hide-details :disabled="!pairReady || busy"
                                label="Первые и последние углы соответствуют одним точкам доски" />
                        </div>
                        <v-divider />
                        <div class="d-flex flex-column ga-2">
                            <strong>Куда сохранить следующую пару?</strong>
                            <v-switch v-model="validation" hide-details :disabled="busy"
                                :label="validation ? 'Контрольная пара' : 'Обучающая пара'" />
                            <span class="text-body-2">Контрольные кадры не используются при обучении; они нужны для проверки результата.</span>
                        </div>
                        <div class="d-flex align-center flex-wrap ga-3">
                            <v-btn prepend-icon="mdi-content-save-plus" :disabled="!pairReady || !orientationConfirmed || busy"
                                @click="capture">Сохранить {{ validation ? 'контрольную' : 'обучающую' }} пару</v-btn>
                            <span v-if="!pairReady" class="text-body-2">Сначала получите кадры, на которых видны углы доски.</span>
                            <span v-else-if="!orientationConfirmed" class="text-body-2">Перед сохранением подтвердите соответствие углов.</span>
                        </div>
                    </v-card-text>
                </v-card>

                <v-card variant="outlined">
                    <v-card-title>2. Рассчитайте калибровку</v-card-title>
                    <v-card-text class="d-flex flex-column ga-3">
                        <p class="text-body-2">Для расчёта требуются как минимум 15 обучающих и 3 контрольные пары. После расчёта проверьте качество на новых кадрах.</p>
                        <div class="d-flex align-center flex-wrap ga-3">
                            <v-btn prepend-icon="mdi-calculator" :loading="calculating"
                                :disabled="busy || state.training_pairs < 15 || state.validation_pairs < 3"
                                @click="calculate">Рассчитать калибровку</v-btn>
                            <span v-if="state.training_pairs < 15 || state.validation_pairs < 3" class="text-body-2">
                                Осталось: {{ Math.max(0, 15 - state.training_pairs) }} обучающих и
                                {{ Math.max(0, 3 - state.validation_pairs) }} контрольных пар.
                            </span>
                        </div>
                    </v-card-text>
                </v-card>
            </template>

            <v-card v-if="state.result" variant="outlined">
                <v-card-title class="d-flex align-center justify-space-between flex-wrap ga-2">
                    <span>Результат калибровки</span>
                    <v-chip :color="state.result.status === 'validated' ? 'success' : state.result.status === 'invalidated' ? 'error' : 'warning'">
                        {{ state.result.status === 'validated' ? 'Качество подтверждено' : state.result.status === 'invalidated' ? 'Недействительна' : 'Ожидает проверки' }}
                    </v-chip>
                </v-card-title>
                <v-card-text class="d-flex flex-column ga-3">
                    <span class="text-body-2">Рассчитана: {{ new Date(state.result.created_at).toLocaleString('ru-RU') }}</span>
                    <div class="calibration-metrics">
                        <div v-for="metric in metrics" :key="metric.label" class="d-flex flex-column ga-1">
                            <span class="text-body-2">{{ metric.label }}</span>
                            <strong>{{ metric.value }}</strong>
                        </div>
                    </div>
                    <v-divider />
                    <div class="d-flex align-center flex-wrap ga-3">
                        <v-btn prepend-icon="mdi-image-search" :disabled="busy" @click="reviewPair()">
                            Посмотреть контрольные кадры
                        </v-btn>
                        <v-select v-if="review" :model-value="review.pair_index" :items="review.pair_indices"
                            label="Контрольная пара" hide-details variant="outlined" :disabled="busy"
                            style="max-width: 240px" @update:model-value="reviewPair" />
                        <span v-if="review?.delta_ms != null" class="text-body-2">
                            Разница получения: {{ review.delta_ms.toFixed(1) }} мс
                        </span>
                    </div>
                    <div v-if="review || state.rectified_previews" class="calibration-images">
                        <div v-for="role in roles" :key="role" style="min-width: 0">
                            <strong>{{ role === 'primary' ? 'Основная камера' : 'Дополнительная камера' }}</strong>
                            <div class="calibration-image mt-2">
                                <img :src="(review?.previews || state.rectified_previews)[role]"
                                    :alt="`Кадр после выравнивания: ${role}`">
                            </div>
                        </div>
                    </div>
                </v-card-text>
            </v-card>

            <template v-if="state.active">
                <v-card variant="outlined">
                    <v-card-title>3. Проверьте качество на новых кадрах</v-card-title>
                    <v-card-text class="d-flex flex-column ga-3">
                        <p class="text-body-2">После расчёта снимите доску ещё в трёх разных положениях, не сохраняя эти пары как обучающие. Проверьте геометрию каждой пары, затем подтвердите качество.</p>
                        <v-text-field v-model="calibrationId" label="Номер сохранённой калибровки"
                            variant="outlined" hide-details :disabled="busy" />
                        <span class="text-body-2">Номер автоматически заполняется после расчёта. При необходимости можно указать номер ранее сохранённой калибровки.</span>
                        <v-checkbox v-model="mountingConfirmed" hide-details :disabled="busy"
                            label="Крепление, фокус и режим камер не менялись после калибровки" />
                        <div class="d-flex align-center flex-wrap ga-3">
                            <v-btn prepend-icon="mdi-camera-refresh" variant="outlined" :loading="busy"
                                @click="observe">Получить независимую пару</v-btn>
                            <v-chip variant="outlined">Проверено в этой вкладке: {{ independentChecks.length }} / 3</v-chip>
                        </div>
                        <div v-if="observation" class="calibration-images">
                            <div v-for="role in roles" :key="role" style="min-width: 0">
                                <strong>{{ role === 'primary' ? 'Основная камера' : 'Дополнительная камера' }}</strong>
                                <div class="calibration-image mt-2">
                                    <img v-if="observation.previews[role]" :src="observation.previews[role]"
                                        :alt="`Независимая пара: ${role}`">
                                    <v-icon v-else icon="mdi-chess-board" size="48" color="grey" />
                                </div>
                            </div>
                        </div>
                        <v-checkbox v-model="orientationConfirmed" hide-details :disabled="!pairReady || busy"
                            label="Углы доски на двух кадрах соответствуют друг другу" />
                        <v-btn prepend-icon="mdi-ruler"
                            :disabled="!pairReady || !orientationConfirmed || !mountingConfirmed || !calibrationId || busy"
                            @click="verifyPair">Проверить геометрию пары</v-btn>
                        <div v-if="geometry" class="calibration-metrics">
                            <div v-for="metric in geometryMetrics" :key="metric.label" class="d-flex flex-column ga-1">
                                <span class="text-body-2">{{ metric.label }}</span><strong>{{ metric.value }}</strong>
                            </div>
                        </div>
                        <v-divider />
                        <v-checkbox v-model="reviewConfirmed" hide-details :disabled="busy"
                            label="Независимые пары сняты в разных положениях, размер клетки и выравнивание проверены" />
                        <v-btn class="quality-button" prepend-icon="mdi-check-decagram"
                            :disabled="busy || !mountingConfirmed || !reviewConfirmed || !calibrationId"
                            @click="validateCalibration">Подтвердить качество калибровки</v-btn>
                    </v-card-text>
                </v-card>

                <v-expansion-panels multiple>
                    <v-expansion-panel>
                        <v-expansion-panel-title>Дополнительно · плоскостность и шум глубины</v-expansion-panel-title>
                        <v-expansion-panel-text>
                            <div class="d-flex flex-column ga-3">
                                <p class="text-body-2">Закрепите доску неподвижно. Снимите новую пару и проверьте стабильность измеряемой глубины.</p>
                                <v-btn variant="outlined" prepend-icon="mdi-camera-refresh" :loading="busy" @click="observe">
                                    Получить пару для измерения
                                </v-btn>
                                <v-chip v-if="observation" variant="outlined">
                                    {{ pairReady ? 'Доска найдена на двух кадрах' : 'Доска не найдена на обоих кадрах' }}
                                </v-chip>
                                <v-checkbox v-model="orientationConfirmed" hide-details :disabled="!pairReady || busy"
                                    label="Углы доски на двух кадрах соответствуют друг другу" />
                                <v-checkbox v-model="stationaryConfirmed" hide-details :disabled="busy"
                                    label="Доска неподвижно закреплена на время серии" />
                                <v-btn class="quality-button" prepend-icon="mdi-chart-timeline-variant" :loading="measuringQuality"
                                    :disabled="busy || !pairReady || !orientationConfirmed || !mountingConfirmed || !stationaryConfirmed || !calibrationId"
                                    @click="measureQuality">Измерить плоскостность и шум глубины</v-btn>
                                <template v-if="quality">
                                    <v-chip variant="outlined">{{ quality.frames }} пар · {{ quality.elapsed_seconds.toFixed(1) }} с</v-chip>
                                    <div class="calibration-metrics">
                                        <div v-for="metric in qualityMetrics" :key="metric.label" class="d-flex flex-column ga-1">
                                            <span class="text-body-2">{{ metric.label }}</span><strong>{{ metric.value }} мм</strong>
                                        </div>
                                    </div>
                                    <span class="text-body-2">Отчёт: {{ qualityReportId }}</span>
                                </template>
                            </div>
                        </v-expansion-panel-text>
                    </v-expansion-panel>

                    <v-expansion-panel>
                        <v-expansion-panel-title>Дополнительно · задержка между камерами</v-expansion-panel-title>
                        <v-expansion-panel-text>
                            <div class="d-flex flex-column ga-3">
                                <p class="text-body-2">Двигайте доску вверх и вниз, несколько раз меняя направление движения. Измерение длится 20 секунд и оценивает относительную задержку программного захвата.</p>
                                <v-checkbox v-model="motionConfirmed" hide-details :disabled="busy"
                                    label="Доска готова к движению со сменой направления" />
                                <v-btn class="quality-button" prepend-icon="mdi-timer-outline" :loading="measuringTiming"
                                    :disabled="busy || !mountingConfirmed || !motionConfirmed || !calibrationId"
                                    @click="measureTiming">Измерить задержку камер · 20 с</v-btn>
                                <v-alert v-if="timingResult" :type="timingResult.status === 'measured' ? 'info' : 'warning'" variant="tonal">
                                    {{ timingResult.status === 'measured' ? 'Относительная задержка оценена · аппаратной синхронизации нет' : timingResult.reason }}
                                </v-alert>
                                <div v-if="timingResult?.estimate" class="calibration-metrics">
                                    <div><span>Поправка времени дополнительной камеры</span>
                                        <strong class="d-block">{{ timingResult.estimate.offset_ms.toFixed(1) }} мс</strong></div>
                                    <div><span>Эмпирическая неопределённость</span>
                                        <strong class="d-block">{{ timingResult.estimate.uncertainty_ms.toFixed(1) }} мс</strong></div>
                                    <div><span>Ошибка совпадения траекторий</span>
                                        <strong class="d-block">{{ timingResult.estimate.residual_rms_px.toFixed(2) }} px</strong></div>
                                </div>
                                <span v-if="timingResult" class="text-body-2" style="overflow-wrap: anywhere">
                                    Отчёт времени: {{ timingResult.report_id }}
                                </span>
                                <v-checkbox v-model="timingConfirmed" hide-details :disabled="busy"
                                    label="Свет и настройки камер не менялись после теста времени" />
                            </div>
                        </v-expansion-panel-text>
                    </v-expansion-panel>

                    <v-expansion-panel>
                        <v-expansion-panel-title>Дополнительно · геометрия лица</v-expansion-panel-title>
                        <v-expansion-panel-text>
                            <div class="d-flex flex-column ga-3">
                                <v-switch v-model="checkTiming" hide-details :disabled="busy"
                                    label="Проверять временную точность" />
                                <v-alert v-if="!checkTiming" type="warning" variant="tonal">
                                    Статический эксперимент. Объект и камеры должны быть неподвижны.
                                    Временная точность не проверяется, живость не оценивается.
                                </v-alert>
                                <v-alert v-else-if="!timingConfirmed" type="info" variant="tonal">
                                    Для измерения геометрии лица необходимо подтвердить условия после теста времени в разделе выше.
                                </v-alert>
                                <v-switch v-model="denseDepth" hide-details :disabled="busy || measuringFace || checkTiming"
                                    label="Карта глубины StereoSGBM" />
                                <template v-if="denseDepth">
                                    <v-text-field v-model.number="faceSeriesCount" type="number" min="2" max="10" step="1"
                                        label="Успешных кадров в серии" variant="outlined" hide-details :disabled="busy || measuringFace" />
                                    <v-checkbox v-model="faceStationary" hide-details :disabled="busy || measuringFace"
                                        label="Образец и камеры неподвижны во время серии" />
                                </template>
                                <div class="calibration-metrics">
                                    <v-select v-model="faceSampleType" :items="faceSamples" item-title="title" item-value="value"
                                        label="Тип предъявления" variant="outlined" hide-details :disabled="busy" />
                                    <v-select v-model="faceLighting" :items="lightingOptions" item-title="title" item-value="value"
                                        label="Освещение" variant="outlined" hide-details :disabled="busy" />
                                    <v-text-field v-model.number="faceDistance" type="number" min="1" step="1"
                                        label="Примерное расстояние, см" variant="outlined" hide-details :disabled="busy" />
                                </div>
                                <v-checkbox v-model="faceConsent" hide-details :disabled="busy"
                                    label="Участник согласен на опыт и обработку изображения лица" />
                                <v-btn prepend-icon="mdi-face-recognition" :loading="measuringFace"
                                    :disabled="busy || measuringFace || !mountingConfirmed || !calibrationId || !faceConsent || !validFaceDistance || !validFaceSeries || (denseDepth && !faceStationary) || (checkTiming && !timingConfirmed)"
                                    @click="measureFace">{{ measuringFace ? 'Получение кадров и измерение' : 'Измерить геометрию лица' }}</v-btn>
                                <v-btn v-if="measuringFace" prepend-icon="mdi-stop" variant="outlined"
                                    :disabled="faceStopRequested" @click="stopFaceMeasurement">Остановить измерение</v-btn>
                                <span v-if="faceAttempts" class="text-body-2">Попыток измерения: {{ faceAttempts }}</span>
                                <template v-if="denseDepth && faceAttempts">
                                    <span>Успешных кадров серии: {{ faceSeriesResults.length }} / {{ faceSeriesCount }}</span>
                                    <div v-for="metric in faceSeriesSummary" :key="metric.label" class="text-body-2">
                                        {{ metric.label }}: среднее {{ metric.mean }} мм · СКО {{ metric.std }} мм · размах {{ metric.range }} мм
                                    </div>
                                    <v-btn prepend-icon="mdi-download" variant="outlined" @click="downloadFaceSeries">Скачать отчёт серии</v-btn>
                                </template>
                                <template v-if="faceResult">
                                    <v-chip v-if="faceResult.measurement_mode === 'static_diagnostic'" color="warning" variant="outlined">
                                        Временная точность не проверена
                                    </v-chip>
                                    <v-alert :type="faceResult.status === 'measured' ? 'info' : 'warning'" variant="tonal">
                                        {{ faceResult.status === 'measured' ? 'Измерено · Живость не оценивалась' :
                                            `Невозможно измерить: ${faceResult.reason}` }}
                                    </v-alert>
                                    <div v-if="faceResult.diagnostics" class="calibration-metrics">
                                        <div class="d-flex flex-column ga-1">
                                            <span>Наибольшее расхождение после выравнивания</span>
                                            <strong>{{ faceResult.diagnostics.vertical_max_px.toFixed(2) }} px
                                                / предел {{ faceResult.diagnostics.vertical_limit_px.toFixed(2) }} px</strong>
                                        </div>
                                        <div class="d-flex flex-column ga-1">
                                            <span>Точка №{{ faceResult.diagnostics.worst_point_number }} · Красная отметка</span>
                                            <strong>{{ faceResult.diagnostics.worst_point_name }}</strong>
                                        </div>
                                        <div class="d-flex flex-column ga-1">
                                            <span>Точек выше допустимого расхождения</span>
                                            <strong>{{ faceResult.diagnostics.exceeding_points }} из 31</strong>
                                        </div>
                                    </div>
                                    <v-alert v-if="faceResult.preview_error" type="warning" variant="tonal">
                                        Не удалось подготовить разметку: {{ faceResult.preview_error }}
                                    </v-alert>
                                    <div v-if="faceResult.previews?.primary && faceResult.previews?.secondary" class="calibration-images">
                                        <div v-for="role in roles" :key="role" style="min-width: 0">
                                            <strong>{{ role === 'primary' ? 'Основная камера' : 'Дополнительная камера' }} · Исходный кадр</strong>
                                            <div class="calibration-image mt-2">
                                                <img :src="faceResult.previews[role]" :alt="`Точки лица: ${role}`">
                                            </div>
                                        </div>
                                    </div>
                                    <h4 v-if="faceResult.dense_depth && faceResult.metrics" class="text-subtitle-1">Landmarks · 31 точка</h4>
                                    <div v-if="faceResult.metrics" class="calibration-metrics">
                                        <div v-for="metric in faceMetrics" :key="metric.label" class="d-flex flex-column ga-1">
                                            <span>{{ metric.label }}</span><strong>{{ metric.value }}</strong>
                                        </div>
                                    </div>
                                    <template v-if="faceResult.dense_depth">
                                        <h4 class="text-subtitle-1">StereoSGBM · внутренняя область лица</h4>
                                        <span>Пригодных пикселей: {{ (faceResult.dense_depth.valid_fraction * 100).toFixed(1) }} %</span>
                                        <div v-if="faceResult.dense_depth.metrics" class="calibration-metrics">
                                            <div><span>RMS отклонения от плоскости</span><strong class="d-block">{{ faceResult.dense_depth.metrics.plane_rms_mm.toFixed(2) }} мм</strong></div>
                                            <div><span>95-й перцентиль отклонения</span><strong class="d-block">{{ faceResult.dense_depth.metrics.plane_p95_mm.toFixed(2) }} мм</strong></div>
                                            <div><span>Разность носа и глаз относительно плоскости</span><strong class="d-block">{{ faceResult.dense_depth.metrics.nose_eye_plane_difference_mm.toFixed(2) }} мм</strong></div>
                                        </div>
                                        <div class="calibration-metrics">
                                            <div v-if="faceResult.previews?.dense_depth">
                                                <span>Глубина, {{ faceResult.dense_depth.depth_display_range_mm.join('–') }} мм</span>
                                                <img :src="faceResult.previews.dense_depth" alt="Карта глубины StereoSGBM" style="width: 100%; display: block" />
                                            </div>
                                            <div v-if="faceResult.previews?.dense_relief">
                                                <span>Рельеф относительно плоскости, −30…+30 мм · чёрное: нет данных</span>
                                                <img :src="faceResult.previews.dense_relief" alt="Отклонение плотной поверхности от плоскости" style="width: 100%; display: block" />
                                            </div>
                                        </div>
                                    </template>
                                    <span class="text-body-2">Время {{ faceResult.elapsed_seconds.toFixed(2) }} с · Разница получения кадров
                                        {{ faceResult.delta_ms == null ? '—' : faceResult.delta_ms.toFixed(1) + ' мс' }}</span>
                                    <span v-if="faceResult.pair_selection" class="text-body-2">
                                        Проверено пар: {{ faceResult.pair_selection.checked_pairs }} · Пропущено:
                                        {{ faceResult.pair_selection.skipped_pairs }} · Ожидание:
                                        {{ faceResult.pair_selection.wait_seconds.toFixed(2) }} с
                                    </span>
                                    <span v-if="faceResult.actual_fps" class="text-body-2">
                                        Средний FPS с начала захвата: основная {{ formatFps(faceResult.actual_fps.primary) }} ·
                                        дополнительная {{ formatFps(faceResult.actual_fps.secondary) }}
                                    </span>
                                    <span class="text-body-2" style="overflow-wrap: anywhere">Отчёт: {{ faceResult.report_id }}</span>
                                </template>
                            </div>
                        </v-expansion-panel-text>
                    </v-expansion-panel>
                </v-expansion-panels>

                <div class="d-flex align-center justify-space-between flex-wrap ga-3">
                    <span class="text-body-2">Завершение сессии возвращает систему из режима калибровки.</span>
                    <v-btn prepend-icon="mdi-stop" variant="outlined" :disabled="busy" @click="finish">
                        Завершить сессию
                    </v-btn>
                </div>
            </template>
        </template>
    </section>
</template>

<script>
export default {
    name: 'StereoCalibration',
    data() {
        return {
            token: '', authorized: false, busy: false, calculating: false, error: '',
            stationaryConfirmed: false, measuringQuality: false, quality: null, qualityReportId: '',
            reviewConfirmed: false, independentChecks: [],
            motionConfirmed: false, timingConfirmed: false, checkTiming: false, measuringTiming: false, timingResult: null,
            faceConsent: false, measuringFace: false, faceResult: null, faceDistance: 60,
            faceStopRequested: false, faceController: null, faceAttempts: 0,
            denseDepth: false, faceStationary: false, faceSeriesCount: 5,
            faceSeriesResults: [], faceAttemptReports: [], faceSeriesId: null,
            faceSampleType: 'live', faceLighting: 'daylight',
            faceSamples: [{ title: 'Настоящее лицо', value: 'live' }, { title: 'Распечатка', value: 'print' },
                { title: 'Фото на телефоне', value: 'phone_photo' }, { title: 'Видео на телефоне', value: 'phone_video' }],
            lightingOptions: [{ title: 'Дневное', value: 'daylight' },
                { title: 'Искусственное', value: 'artificial' }, { title: 'Смешанное', value: 'mixed' }],
            mountingConfirmed: false, orientationConfirmed: false, validation: false,
            rotation: 0, observation: null, review: null, geometry: null, calibrationId: '', squareMm: 45, roles: ['primary', 'secondary'],
            rotations: [0, 1, 2, 3].map(value => ({ value, title: `${value * 90}°` })),
            state: { active: false, session_id: null, training_pairs: 0, validation_pairs: 0, result: null }
        };
    },
    mounted() { this.connect(); },
    beforeUnmount() { this.stopFaceMeasurement(); },
    watch: {
        faceSampleType: 'clearFaceResult',
        faceLighting: 'clearFaceResult',
        faceDistance: 'clearFaceResult',
        calibrationId() {
            this.clearFaceResult();
            this.independentChecks = [];
            this.reviewConfirmed = false;
            this.timingResult = null;
            this.timingConfirmed = false;
            this.quality = null;
            this.qualityReportId = '';
        },
        mountingConfirmed: 'clearFaceResult',
        faceConsent: 'clearFaceResult',
        timingConfirmed: 'clearFaceResult',
        checkTiming() {
            if (this.checkTiming) this.denseDepth = false;
            this.clearFaceResult();
        },
        denseDepth: 'clearFaceResult',
        faceStationary: 'clearFaceResult',
        faceSeriesCount: 'clearFaceResult'
    },
    computed: {
        validFaceSeries() {
            return !this.denseDepth || (Number.isInteger(this.faceSeriesCount) && this.faceSeriesCount >= 2 && this.faceSeriesCount <= 10);
        },
        faceSeriesSummary() {
            if (!this.faceSeriesResults.length) return [];
            return [['Глубина', 'mean_depth_mm'], ['RMS плоскости', 'plane_rms_mm'],
                ['Разность носа и глаз', 'nose_eye_plane_difference_mm']].map(([label, key]) => {
                const values = this.faceSeriesResults.map(item => item.dense_depth.metrics[key]);
                const mean = values.reduce((sum, value) => sum + value, 0) / values.length;
                const variance = values.reduce((sum, value) => sum + (value - mean) ** 2, 0);
                return { label, mean: mean.toFixed(2),
                    std: values.length > 1 ? Math.sqrt(variance / (values.length - 1)).toFixed(2) : '—',
                    range: (Math.max(...values) - Math.min(...values)).toFixed(2) };
            });
        },
        validFaceDistance() {
            return typeof this.faceDistance === 'number' && Number.isFinite(this.faceDistance) && this.faceDistance > 0;
        },
        faceMetrics() {
            const metrics = this.faceResult?.metrics;
            if (!metrics) return [];
            return [['Средняя глубина', 'mean_depth_mm', 'мм'],
                ['Среднее отклонение от плоскости', 'plane_mean_mm', 'мм'],
                ['RMS отклонения от плоскости', 'plane_rms_mm', 'мм'],
                ['Максимальное отклонение', 'plane_max_mm', 'мм'],
                ['Разность носа и глаз относительно плоскости', 'nose_eye_plane_difference_mm', 'мм'],
                ['Среднее расхождение по вертикали', 'vertical_mean_px', 'px'],
                ['Максимальное расхождение по вертикали', 'vertical_max_px', 'px'],
                ['Максимальная ошибка репроекции', 'reprojection_max_px', 'px'],
                ['Оценённая временная ошибка', 'estimated_exposure_error_ms', 'мс'],
                ['Временная погрешность глубины (условная)', 'timing_depth_uncertainty_mm', 'мм'],
                ['Наблюдаемая скорость точек', 'observed_image_speed_px_s', 'px/с']]
                .filter(([, key]) => metrics[key] != null)
                .map(([label, key, unit]) => ({ label, value: `${Number(metrics[key]).toFixed(2)} ${unit}` }));
        },
        validSquare() {
            return typeof this.squareMm === 'number' && Number.isFinite(this.squareMm) && this.squareMm > 0;
        },
        geometryMetrics() {
            if (!this.geometry) return [];
            return [['Средняя сторона клетки', 'mean_length_mm', 'мм'],
                [`Средняя ошибка относительно ${this.geometry.expected_mm} мм`, 'mean_error_mm', 'мм'],
                ['Максимальная ошибка', 'max_error_mm', 'мм'],
                ['Средняя относительная ошибка', 'mean_error_percent', '%'],
                ['Среднее отклонение от плоскости', 'plane_mean_mm', 'мм'],
                ['RMS отклонения от плоскости', 'plane_rms_mm', 'мм'],
                ['Максимальное отклонение от плоскости', 'plane_max_mm', 'мм']]
                .filter(([, key]) => this.geometry[key] != null)
                .map(([label, key, unit]) => ({ label, value: `${Number(this.geometry[key]).toFixed(2)} ${unit}` }));
        },
        qualityMetrics() {
            if (!this.quality) return [];
            return [['Среднее отклонение от плоскости', 'plane_mean_mm'],
                ['RMS отклонения от плоскости', 'plane_rms_mm'],
                ['Максимальное отклонение от плоскости', 'plane_max_mm'],
                ['Средняя глубина доски', 'mean_depth_mm'],
                ['Среднее СКО глубины углов', 'point_depth_std_mean_mm'],
                ['Максимальное СКО глубины угла', 'point_depth_std_max_mm'],
                ['СКО глубины центра доски', 'center_depth_std_mm'],
                ['Размах глубины центра доски', 'center_depth_range_mm']]
                .map(([label, key]) => ({ label, value: Number(this.quality[key]).toFixed(3) }));
        },
        pairReady() {
            return this.observation?.found.primary && this.observation?.found.secondary;
        },
        metrics() {
            const m = this.state.result?.metrics;
            if (!m) return [];
            return [
                ['Основная RMS', m.primary_rms_px, 'px'],
                ['Дополнительная RMS', m.secondary_rms_px, 'px'],
                ['Стерео RMS', m.stereo_rms_px, 'px'],
                ['Контроль: среднее по вертикали', m.validation_vertical_mean_px, 'px'],
                ['Контроль: максимум по вертикали', m.validation_vertical_max_px, 'px'],
                ['Контроль: репроекция второй камеры', m.validation_reprojection_mean_px, 'px'],
                ['Расчётная база', m.baseline_mm, 'мм']
            ].map(([label, value, unit]) => ({ label, value: `${Number(value).toFixed(2)} ${unit}` }));
        }
    },
    methods: {
        async measureTiming() {
            this.timingResult = null;
            this.timingConfirmed = false;
            this.faceResult = null;
            this.measuringTiming = true;
            const data = await this.request('timing', { session_id: this.state.session_id,
                calibration_id: this.calibrationId, mounting_confirmed: this.mountingConfirmed,
                motion_confirmed: this.motionConfirmed, rotation: this.rotation });
            this.clearObservation();
            if (data) this.timingResult = data;
            this.measuringTiming = false;
        },
        async validateCalibration() {
            const data = await this.request('validate', { session_id: this.state.session_id,
                calibration_id: this.calibrationId, mounting_confirmed: this.mountingConfirmed,
                review_confirmed: this.reviewConfirmed });
            if (data) this.state = data;
        },
        formatFps(value) {
            return typeof value === 'number' && Number.isFinite(value) ? value.toFixed(1) : 'нет данных';
        },
        clearFaceResult() {
            if (this.measuringFace) this.stopFaceMeasurement();
            this.faceResult = null;
            this.faceSeriesResults = [];
            this.faceAttemptReports = [];
        },
        stopFaceMeasurement() {
            this.faceStopRequested = true;
            this.faceController?.abort();
        },
        async measureFace() {
            if (this.measuringFace || this.busy) return;
            this.faceResult = null;
            this.faceAttempts = 0;
            this.faceSeriesResults = [];
            this.faceAttemptReports = [];
            this.faceSeriesId = crypto.randomUUID().replaceAll('-', '');
            this.faceStopRequested = false;
            this.measuringFace = true;
            this.clearObservation();
            const body = { session_id: this.state.session_id,
                calibration_id: this.calibrationId, mounting_confirmed: this.mountingConfirmed,
                consent_confirmed: this.faceConsent, sample_type: this.faceSampleType,
                lighting: this.faceLighting, distance_cm: this.faceDistance, timing_confirmed: this.timingConfirmed,
                check_timing: this.checkTiming, dense_depth: this.denseDepth,
                stationary_confirmed: this.faceStationary, series_id: this.faceSeriesId };
            const targetCount = this.denseDepth ? this.faceSeriesCount : 1;
            try {
                while (!this.faceStopRequested) {
                    this.faceAttempts++;
                    const data = await this.request('face', body);
                    if (this.faceStopRequested || !data) break;
                    this.faceResult = data;
                    this.faceAttemptReports.push({ report_id: data.report_id, status: data.status,
                        reason: data.reason, delta_ms: data.delta_ms });
                    if (data.status === 'measured') {
                        if (!this.denseDepth) break;
                        if (data.dense_depth?.status !== 'measured') {
                            this.error = 'Backend не вернул карту StereoSGBM. Синхронизируйте файлы и перезапустите backend';
                            break;
                        }
                        const first = this.faceSeriesResults[0];
                        if (first && first.calibration_fingerprint !== data.calibration_fingerprint) {
                            this.error = 'Калибровка изменилась во время серии';
                            break;
                        }
                        const { previews, ...record } = data;
                        this.faceSeriesResults.push(record);
                        if (this.faceSeriesResults.length >= targetCount) break;
                    } else if (data.retryable !== true) break;
                    // Небольшая пауза между запросами, без параллельных измерений
                    await new Promise(resolve => window.setTimeout(resolve, 500));
                }
            } finally {
                this.measuringFace = false;
                this.faceController = null;
            }
        },
        downloadFaceSeries() {
            const report = { version: 1, series_id: this.faceSeriesId, diagnostic_only: true,
                decision: 'not_evaluated', timing_verified: false, stationarity_verified: false,
                target_frames: this.faceSeriesCount, attempts: this.faceAttemptReports,
                successful_frames: this.faceSeriesResults, summary: this.faceSeriesSummary };
            const url = URL.createObjectURL(new Blob([JSON.stringify(report, null, 2)], { type: 'application/json' }));
            const link = document.createElement('a');
            link.href = url;
            link.download = `static_stereo_${this.faceSeriesId}.json`;
            link.click();
            window.setTimeout(() => URL.revokeObjectURL(url), 1000);
        },
        async measureQuality() {
            this.quality = null;
            this.measuringQuality = true;
            const data = await this.request('quality', { session_id: this.state.session_id,
                observation_id: this.observation?.observation_id, calibration_id: this.calibrationId,
                orientation_confirmed: this.orientationConfirmed, mounting_confirmed: this.mountingConfirmed,
                stationary: this.stationaryConfirmed });
            this.clearObservation();
            if (data) { this.quality = data.quality; this.qualityReportId = data.report_id; }
            this.measuringQuality = false;
        },
        async verifyPair() {
            this.geometry = null;
            const data = await this.request('verify', { session_id: this.state.session_id,
                observation_id: this.observation?.observation_id, calibration_id: this.calibrationId,
                orientation_confirmed: this.orientationConfirmed, mounting_confirmed: this.mountingConfirmed });
            if (data) {
                this.geometry = data.geometry;
                if (data.independent_check_id && !this.independentChecks.includes(data.independent_check_id)) {
                    this.independentChecks.push(data.independent_check_id);
                }
            }
        },
        async reviewPair(pairIndex = null) {
            this.review = null;
            this.geometry = null;
            const data = await this.request('review', {
                session_id: this.state.result?.session_id, pair_index: pairIndex
            });
            if (data) { this.review = data; this.geometry = data.geometry; }
        },
        async readJson(response) {
            if (!(response.headers.get('Content-Type') || '').includes('application/json')) {
                throw new Error(`API вернул не JSON (HTTP ${response.status}). Проверьте HTTPS-сервер и синхронизацию файлов`);
            }
            return response.json();
        },
        async downloadFrame(role) {
            if (this.busy || !this.observation) return;
            this.busy = true;
            this.error = '';
            const controller = new AbortController();
            const timeout = window.setTimeout(() => controller.abort(), 30000);
            try {
                const response = await fetch(`/api/calibration/frame/${role}`, {
                    method: 'POST',
                    headers: { 'X-Calibration-Token': this.token, 'Content-Type': 'application/json' },
                    body: JSON.stringify({ session_id: this.state.session_id,
                        observation_id: this.observation.observation_id }),
                    signal: controller.signal
                });
                if (!response.ok) {
                    const data = await this.readJson(response);
                    throw new Error(data.message || `HTTP ${response.status}`);
                }
                if (!(response.headers.get('Content-Type') || '').includes('image/png')) {
                    throw new Error('Вместо PNG получен другой ответ. Проверьте backend и прокси API');
                }
                const url = URL.createObjectURL(await response.blob());
                const link = document.createElement('a');
                link.href = url;
                link.download = `calibration_${this.observation.observation_id}_${role}.png`;
                document.body.appendChild(link);
                link.click();
                link.remove();
                window.setTimeout(() => URL.revokeObjectURL(url), 1000);
            } catch (error) {
                this.error = error.name === 'AbortError' ? 'Время скачивания истекло' : error.message;
            } finally {
                window.clearTimeout(timeout);
                this.busy = false;
            }
        },
        clearObservation() {
            this.observation = null;
            this.orientationConfirmed = false;
            this.geometry = null;
        },
        async request(action, body) {
            if (this.busy) return null;
            this.busy = true;
            this.error = '';
            const controller = new AbortController();
            if (action === 'face') this.faceController = controller;
            const timeout = window.setTimeout(() => controller.abort(),
                action === 'calculate' ? 180000 : ['quality', 'face', 'timing'].includes(action) ? 90000 : 30000);
            try {
                const response = await fetch(`/api/calibration/${action}`, {
                    method: body ? 'POST' : 'GET',
                    headers: { 'X-Calibration-Token': this.token, 'Content-Type': 'application/json' },
                    body: body ? JSON.stringify(body) : undefined,
                    signal: controller.signal
                });
                const data = await this.readJson(response);
                if (!response.ok) throw new Error(data.message || `HTTP ${response.status}`);
                return data;
            } catch (error) {
                if (!(action === 'face' && this.faceStopRequested)) {
                    this.error = error.name === 'AbortError' ? 'Время ожидания истекло. Обновите состояние сессии' : error.message;
                }
                return null;
            } finally {
                window.clearTimeout(timeout);
                this.busy = false;
                if (action === 'face') this.faceController = null;
            }
        },
        async connect() {
            const data = await this.request('status');
            if (data) {
                this.authorized = true;
                this.state = data;
                this.geometry = null;
                this.review = null;
                if (data.result?.session_id) this.calibrationId = data.result.session_id;
                if (data.active && data.training_pairs >= 15 && data.validation_pairs < 3) this.validation = true;
            }
        },
        async start() {
            const data = await this.request('start', { mounting_confirmed: this.mountingConfirmed, square_mm: this.squareMm });
            if (data) {
                this.state = data;
                this.review = null;
                this.calibrationId = '';
                this.mountingConfirmed = false;
                this.validation = false;
                this.clearObservation();
                this.quality = null;
                this.qualityReportId = '';
                this.faceResult = null;
                this.faceConsent = false;
                this.independentChecks = [];
                this.reviewConfirmed = false;
                this.timingResult = null;
                this.timingConfirmed = false;
            }
        },
        async observe() {
            this.clearObservation();
            const data = await this.request('observe', { session_id: this.state.session_id, rotation: this.rotation });
            if (data) this.observation = data;
        },
        async capture() {
            const data = await this.request('capture', {
                session_id: this.state.session_id, observation_id: this.observation?.observation_id,
                validation: this.validation, orientation_confirmed: this.orientationConfirmed
            });
            if (data) {
                this.state = data;
                this.clearObservation();
                if (data.training_pairs >= 15 && data.validation_pairs < 3) this.validation = true;
            }
        },
        async calculate() {
            this.geometry = null;
            this.review = null;
            this.calculating = true;
            const data = await this.request('calculate', { session_id: this.state.session_id });
            if (data) {
                this.state = data;
                if (data.result?.session_id) this.calibrationId = data.result.session_id;
                this.quality = null;
                this.qualityReportId = '';
            }
            this.calculating = false;
        },
        async finish() {
            const data = await this.request('finish', { session_id: this.state.session_id });
            if (data) { this.state = data; this.clearObservation(); this.faceResult = null; this.faceConsent = false; }
        }
    }
};
</script>

<style scoped>
.calibration { width: min(1100px, 100%); margin: 0 auto; }
.quality-button { max-width: 100%; min-height: 48px; height: auto; padding-top: 8px; padding-bottom: 8px; }
.quality-button :deep(.v-btn__content) { white-space: normal; text-align: center; }
.calibration-images { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 16px; }
.calibration-image { display: flex; align-items: center; justify-content: center; width: 100%; aspect-ratio: 16 / 9; background: #202020; overflow: hidden; }
.calibration-image img { display: block; width: 100%; height: 100%; object-fit: contain; }
.calibration-metrics { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 16px; overflow-wrap: anywhere; }
@media (max-width: 700px) {
    .calibration-images, .calibration-metrics { grid-template-columns: 1fr; }
}
</style>
