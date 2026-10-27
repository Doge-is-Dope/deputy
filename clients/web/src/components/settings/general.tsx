import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import {
  LANGUAGES,
  setLanguage,
  useLanguage,
  useT,
  type Language,
} from "@/lib/i18n"
import { Card, Row, Section } from "@/components/settings/layout"

/** The interface's language: the browser's, or one named in itself. */
export function General() {
  const t = useT()
  const { language } = useLanguage()
  const nameOf = (id: Language) =>
    id === "auto"
      ? t.settings.autoLanguage
      : LANGUAGES.find((each) => each.id === id)!.name
  return (
    <Section>
      <Card>
        <Row label={t.settings.language}>
          <Select
            value={language}
            onValueChange={(value) => setLanguage(value as Language)}
          >
            <SelectTrigger aria-label={t.settings.language}>
              <SelectValue>{nameOf}</SelectValue>
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="auto">{t.settings.autoLanguage}</SelectItem>
              {LANGUAGES.map(({ id, name }) => (
                <SelectItem key={id} value={id} lang={id}>
                  {name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </Row>
      </Card>
    </Section>
  )
}
