import Foundation
import EventKit

func emit(_ value: [String: Any], _ code: Int32 = 0) -> Never {
    if let data = try? JSONSerialization.data(withJSONObject: value, options: [.sortedKeys]) {
        FileHandle.standardOutput.write(data)
        FileHandle.standardOutput.write(Data([10]))
    }
    exit(code)
}
func fail(_ code: String) -> Never { emit(["ok": false, "error_code": code], 1) }
let args = Array(CommandLine.arguments.dropFirst())
guard let command = args.first, ["status", "authorize", "lists", "read"].contains(command) else { fail("invalid_request") }
guard (command == "read" && args.count == 3) || (command != "read" && args.count == 1) else { fail("invalid_request") }
let authorization = EKEventStore.authorizationStatus(for: .reminder)
func statusName(_ status: EKAuthorizationStatus) -> String {
    switch status {
    case .notDetermined: return "not_determined"
    case .restricted: return "restricted"
    case .denied: return "denied"
    case .fullAccess: return "authorized"
    default: return "unsupported"
    }
}
if command == "status" { emit(["ok": true, "authorization": statusName(authorization)]) }
let store = EKEventStore()
// Timeout exits without exposing EventKit errors or personal data.
DispatchQueue.main.asyncAfter(deadline: .now() + (command == "authorize" ? 55 : 15)) { fail("timeout") }
if command == "authorize" {
    store.requestFullAccessToReminders { granted, _ in
        emit(["ok": granted, "authorization": statusName(EKEventStore.authorizationStatus(for: .reminder))], granted ? 0 : 1)
    }
} else {
    guard authorization == .fullAccess else { fail("permission_required") }
    if command == "lists" {
        let lists = store.calendars(for: .reminder).map { ["id": $0.calendarIdentifier, "title": String($0.title.prefix(256))] }
        emit(["ok": true, "lists": Array(lists.prefix(100)), "truncated": lists.count > 100])
    }
    guard let limit = Int(args[2]), (1...20).contains(limit) else { fail("invalid_limit") }
    guard let calendar = store.calendar(withIdentifier: args[1]), calendar.allowedEntityTypes.contains(.reminder) else { fail("list_not_found") }
    let predicate = store.predicateForIncompleteReminders(withDueDateStarting: nil, ending: nil, calendars: [calendar])
    store.fetchReminders(matching: predicate) { fetched in
        guard let fetched = fetched else { fail("fetch_failed") }
        let items = fetched.filter { !$0.isCompleted && $0.calendar.calendarIdentifier == args[1] }.sorted {
            let left = $0.dueDateComponents?.date ?? .distantFuture
            let right = $1.dueDateComponents?.date ?? .distantFuture
            return left == right ? $0.calendarItemIdentifier < $1.calendarItemIdentifier : left < right
        }
        let rows: [[String: Any]] = items.prefix(limit).map { reminder in
            var due: [String: Int] = [:]
            if let d = reminder.dueDateComponents {
                due["year"] = d.year; due["month"] = d.month; due["day"] = d.day
                due["hour"] = d.hour; due["minute"] = d.minute
            }
            return ["id": reminder.calendarItemIdentifier, "title": String((reminder.title ?? "").prefix(512)), "due": due, "completed": false]
        }
        emit(["ok": true, "list_id": args[1], "items": rows, "truncated": items.count > limit])
    }
}
RunLoop.main.run()
