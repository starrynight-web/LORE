import { Alert, AlertDescription } from "@/components/ui/alert"

export function ErrorAlert({ message }: { message: string }) {
  if (!message) return null
  return (
    <Alert variant="destructive">
      <AlertDescription>{message}</AlertDescription>
    </Alert>
  )
}
