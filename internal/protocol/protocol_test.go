package protocol

import (
	"encoding/json"
	"reflect"
	"testing"
)

// Le hub (Python) lit ces lignes JSON : les noms des champs sont un contrat, ils ne doivent pas changer.
func TestEventJSONContract(t *testing.T) {
	b, err := json.Marshal(Event{Type: "message", ThreadID: 42, MessageID: "m1", SenderID: 7, Text: "salut", TimeMs: 1700000000000,
		FromMe: true, History: true, E2EE: true, Chat: "42@msgr"})
	if err != nil {
		t.Fatal(err)
	}
	var got map[string]any
	if err := json.Unmarshal(b, &got); err != nil {
		t.Fatal(err)
	}
	want := map[string]any{"type": "message", "thread": 42.0, "id": "m1", "sender": 7.0, "text": "salut", "ts": 1.7e12,
		"from_me": true, "history": true, "e2ee": true, "chat": "42@msgr"}
	if !reflect.DeepEqual(got, want) {
		t.Fatalf("contrat JSON de Event modifié :\n got  %v\n want %v", got, want)
	}
}

func TestEventOmitsOptionalFields(t *testing.T) {
	b, _ := json.Marshal(Event{Type: "message", ThreadID: 1})
	var got map[string]any
	_ = json.Unmarshal(b, &got)
	for _, k := range []string{"history", "e2ee", "chat"} {
		if _, ok := got[k]; ok {
			t.Errorf("le champ optionnel %q ne doit pas être émis quand il est vide", k)
		}
	}
	for _, k := range []string{"type", "thread", "id", "sender", "text", "ts", "from_me"} {
		if _, ok := got[k]; !ok {
			t.Errorf("le champ obligatoire %q doit toujours être émis", k)
		}
	}
}

// Les ordres envoyés par le hub, tels que hub.py les écrit.
func TestCommandJSONContract(t *testing.T) {
	cases := map[string]Command{
		`{"thread":42,"text":"ok"}`:                                         {ThreadID: 42, Text: "ok"},
		`{"chat":"42@msgr","text":"ok"}`:                                    {Chat: "42@msgr", Text: "ok"},
		`{"op":"fetch","thread":42,"ref_ts":5,"ref_id":"x"}`:                {Op: "fetch", ThreadID: 42, RefTs: 5, RefID: "x"},
		`{"op":"history_enroll","pin":"123456"}`:                            {Op: "history_enroll", PIN: "123456"},
		`{"op":"history_fetch","chat":"42","before":9,"count":30}`:          {Op: "history_fetch", Chat: "42", Before: 9, Count: 30},
		`{"op":"media","req":"ab12","blob":"k","mtype":"image","max":1000}`: {Op: "media", Req: "ab12", Blob: "k", MType: "image", Max: 1000},
		`{"op":"typing","thread":42,"kind":1,"on":true}`:                    {Op: "typing", ThreadID: 42, Kind: 1, On: true},
	}
	for in, want := range cases {
		var got Command
		if err := json.Unmarshal([]byte(in), &got); err != nil {
			t.Fatalf("%s : %v", in, err)
		}
		if !reflect.DeepEqual(got, want) {
			t.Errorf("%s\n got  %+v\n want %+v", in, got, want)
		}
	}
}
