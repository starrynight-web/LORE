import { Card, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"

export default function LockedPage() {
  return (
    <div className="flex min-h-svh items-center justify-center bg-background p-6">
      <Card className="w-full max-w-md">
        <CardHeader>
          <CardDescription>Lore</CardDescription>
          <CardTitle>
            <h1>Open the link printed in the terminal.</h1>
          </CardTitle>
        </CardHeader>
      </Card>
    </div>
  )
}
