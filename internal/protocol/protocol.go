// Package protocol décrit le contrat JSON entre ce client et le hub :
//   - Event : ligne écrite sur la sortie standard (le hub la lit) ;
//   - Command : ligne reçue sur l'entrée standard (le hub l'envoie).
package protocol

// Event : message ou évènement envoyé au hub (une ligne JSON par évènement).
type Event struct {
	Type      string `json:"type"`
	ThreadID  int64  `json:"thread"`
	MessageID string `json:"id"`
	SenderID  int64  `json:"sender"`
	Text      string `json:"text"`
	TimeMs    int64  `json:"ts"`
	FromMe    bool   `json:"from_me"`
	History   bool   `json:"history,omitempty"` // true = message de l'historique chargé au démarrage
	E2EE      bool   `json:"e2ee,omitempty"`    // true = reçu par le canal chiffré
	Chat      string `json:"chat,omitempty"`    // JID du chat chiffré (pour répondre)
}

// Command : ordre reçu du hub (envoi, historique, média, « en train d'écrire »…).
type Command struct {
	ThreadID int64  `json:"thread"`
	Chat     string `json:"chat,omitempty"` // JID d'un chat chiffré
	E2EE     bool   `json:"e2ee,omitempty"` // envoyer par le canal chiffré
	Text     string `json:"text"`
	Op       string `json:"op,omitempty"`     // "fetch" : charger des messages plus anciens d'un fil
	RefTs    int64  `json:"ref_ts,omitempty"` // fetch : horodatage du plus ancien message connu
	RefID    string `json:"ref_id,omitempty"` // fetch : identifiant du plus ancien message connu
	PIN      string `json:"pin,omitempty"`    // history_enroll : jamais journalisé ni stocké
	Before   int64  `json:"before,omitempty"` // history_fetch : messages plus anciens que cet horodatage (ms)
	Count    int    `json:"count,omitempty"`  // history_fetch : taille de page
	Req      string `json:"req,omitempty"`    // media : nom du fichier de sortie (hexadécimal)
	Blob     string `json:"blob,omitempty"`   // media : clés + chemin du média chiffré
	MType    string `json:"mtype,omitempty"`  // media : image | video | audio | document | linkthumb
	Max      int64  `json:"max,omitempty"`    // media : taille maximale acceptée (octets)
	On       bool   `json:"on,omitempty"`     // typing : afficher / retirer « est en train d'écrire »
	Kind     int64  `json:"kind,omitempty"`   // typing : type de fil Messenger (1 = conversation à deux)
}
