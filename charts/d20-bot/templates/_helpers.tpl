{{- define "d20-bot.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{- define "d20-bot.fullname" -}}
{{- if .Values.fullnameOverride }}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- printf "%s-%s" .Release.Name (include "d20-bot.name" .) | trunc 63 | trimSuffix "-" }}
{{- end }}
{{- end }}

{{- define "d20-bot.labels" -}}
helm.sh/chart: {{ printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" }}
app.kubernetes.io/name: {{ include "d20-bot.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{- define "d20-bot.selectorLabels" -}}
app.kubernetes.io/name: {{ include "d20-bot.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{- define "d20-bot.secretName" -}}
{{- default (include "d20-bot.fullname" .) .Values.existingSecret }}
{{- end }}

{{- define "d20-bot.image" -}}
{{- printf "%s:%s" .Values.image.repository (default .Chart.AppVersion .Values.image.tag) }}
{{- end }}

{{- define "d20-bot.pvcName" -}}
{{- default (printf "%s-data" (include "d20-bot.fullname" .)) .Values.core.persistence.existingClaim }}
{{- end }}
