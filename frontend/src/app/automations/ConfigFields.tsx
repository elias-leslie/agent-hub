'use client'

import type {
  Config,
  ConfigField,
  ConfigFieldType,
  ConfigSchema,
  ConfigValue,
} from '@/lib/api/automations'

interface ConfigFieldsProps {
  schema?: ConfigSchema | null
  value: Config
  onChange: (value: Config) => void
  idPrefix: string
}

function currentValue(
  value: ConfigValue | undefined,
  field: ConfigField,
): ConfigValue {
  return value ?? field.default ?? (field.type === 'boolean' ? false : '')
}

function fieldType(field: ConfigField): ConfigFieldType | undefined {
  if (Array.isArray(field.type))
    return field.type.find((type) => type !== 'null')
  if (field.type) return field.type
  return field.anyOf?.map(fieldType).find((type) => type !== 'null')
}

export function ConfigFields({
  schema,
  value,
  onChange,
  idPrefix,
}: ConfigFieldsProps) {
  const fields = Object.entries(schema?.properties ?? {})
  if (fields.length === 0) {
    return (
      <p className="text-sm text-slate-400">
        No additional settings for this workflow.
      </p>
    )
  }

  const update = (key: string, next: ConfigValue) =>
    onChange({ ...value, [key]: next })

  return (
    <div className="grid gap-4 sm:grid-cols-2">
      {fields.map(([key, field]) => {
        const id = `${idPrefix}-${key}`
        const label = field.title || key.replaceAll('_', ' ')
        const selected = currentValue(value[key], field)
        const required = schema?.required?.includes(key) ?? false
        const common = 'control-input mt-1'
        const type = fieldType(field)

        if (key === 'allowed_hours' && type === 'array') {
          const hours = Array.isArray(value[key])
            ? value[key].filter(
                (hour): hour is number => typeof hour === 'number',
              )
            : null
          return (
            <fieldset key={key} className="sm:col-span-2">
              <legend className="text-sm font-medium text-slate-200">
                Allowed hours (UTC)
              </legend>
              <label className="mt-2 flex items-center gap-2 text-xs text-slate-300">
                <input
                  type="checkbox"
                  checked={hours === null}
                  onChange={(event) =>
                    update(key, event.target.checked ? null : [])
                  }
                  className="h-4 w-4 accent-amber-500"
                />
                All hours
              </label>
              {hours !== null && (
                <div className="mt-3 grid grid-cols-4 gap-2 sm:grid-cols-6 md:grid-cols-8">
                  {Array.from({ length: 24 }, (_, hour) => (
                    <label
                      key={hour}
                      className="flex items-center gap-1 text-xs text-slate-300"
                    >
                      <input
                        type="checkbox"
                        checked={hours.includes(hour)}
                        onChange={(event) =>
                          update(
                            key,
                            event.target.checked
                              ? [...hours, hour].sort((a, b) => a - b)
                              : hours.filter((item) => item !== hour),
                          )
                        }
                        className="h-4 w-4 accent-amber-500"
                      />
                      {String(hour).padStart(2, '0')}:00
                    </label>
                  ))}
                </div>
              )}
            </fieldset>
          )
        }

        if (type === 'object' || type === 'array') {
          return (
            <div key={key} className="sm:col-span-2">
              <p className="text-sm font-medium text-slate-300">{label}</p>
              <p className="mt-1 text-xs text-slate-500">
                {field.description ||
                  'This setting is managed by its owning workflow.'}
              </p>
              {value[key] != null && (
                <pre className="mt-2 overflow-x-auto whitespace-pre-wrap break-all rounded-lg bg-slate-900/70 p-2 text-xs text-slate-400">
                  {JSON.stringify(value[key], null, 2)}
                </pre>
              )}
            </div>
          )
        }

        return (
          <div
            key={key}
            className={
              type === 'boolean' || key.includes('message')
                ? 'sm:col-span-2'
                : ''
            }
          >
            {type === 'boolean' ? (
              <label
                htmlFor={id}
                className="flex items-center gap-3 text-sm font-medium text-slate-200"
              >
                <input
                  id={id}
                  type="checkbox"
                  checked={selected === true}
                  onChange={(event) => update(key, event.target.checked)}
                  className="h-4 w-4 accent-amber-500"
                />
                {label}
              </label>
            ) : (
              <label
                htmlFor={id}
                className="block text-sm font-medium text-slate-200"
              >
                {label}
                {field.enum ? (
                  <select
                    id={id}
                    value={String(selected)}
                    onChange={(event) => {
                      const chosen = field.enum?.find(
                        (option) => String(option) === event.target.value,
                      )
                      update(key, chosen ?? event.target.value)
                    }}
                    className="control-select mt-1 w-full"
                    required={required}
                  >
                    <option value="" disabled={required}>
                      {required ? 'Select a value' : 'Use default'}
                    </option>
                    {field.enum.map((option) => (
                      <option key={String(option)} value={String(option)}>
                        {String(option)}
                      </option>
                    ))}
                  </select>
                ) : key.includes('message') && type === 'string' ? (
                  <textarea
                    id={id}
                    rows={4}
                    value={selected === null ? '' : String(selected)}
                    onChange={(event) => update(key, event.target.value)}
                    className={common}
                    required={required}
                  />
                ) : (
                  <input
                    id={id}
                    type={
                      type === 'integer' || type === 'number'
                        ? 'number'
                        : 'text'
                    }
                    step={
                      type === 'integer'
                        ? '1'
                        : type === 'number'
                          ? 'any'
                          : undefined
                    }
                    min={
                      field.minimum ??
                      field.anyOf?.find((option) => option.type === type)
                        ?.minimum
                    }
                    max={
                      field.maximum ??
                      field.anyOf?.find((option) => option.type === type)
                        ?.maximum
                    }
                    value={selected === null ? '' : String(selected)}
                    onChange={(event) =>
                      update(
                        key,
                        type === 'integer' || type === 'number'
                          ? event.target.value === ''
                            ? null
                            : Number(event.target.value)
                          : event.target.value,
                      )
                    }
                    className={common}
                    required={required}
                  />
                )}
              </label>
            )}
            {field.description && (
              <p className="mt-1 text-xs leading-5 text-slate-500">
                {field.description}
              </p>
            )}
          </div>
        )
      })}
    </div>
  )
}
