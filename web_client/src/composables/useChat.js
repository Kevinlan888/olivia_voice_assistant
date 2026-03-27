import { ref, nextTick } from 'vue'

export function useChat(chatElRef) {
  const messages = ref([])
  let _idCtr = 0

  function addMessage(type, text) {
    const id = ++_idCtr
    messages.value.push({ id, type, text })
    nextTick(() => {
      if (chatElRef.value) chatElRef.value.scrollTop = chatElRef.value.scrollHeight
    })
    return id
  }

  function updateMessage(id, text) {
    const m = messages.value.find(m => m.id === id)
    if (m) m.text = text
  }

  function removeMessage(id) {
    const i = messages.value.findIndex(m => m.id === id)
    if (i !== -1) messages.value.splice(i, 1)
  }

  return { messages, addMessage, updateMessage, removeMessage }
}
