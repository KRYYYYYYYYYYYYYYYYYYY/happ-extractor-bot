package main

import (
	"fmt"
	"os"
	// здесь должны быть твои библиотеки для дешифровки crypt4/happ
)

func main() {
	if len(os.Args) < 2 {
		fmt.Println("Ошибка: не передана ссылка")
		return
	}
	happLink := os.Args[1]

	// ТВОЯ ЛОГИКА ДЕШИФРОВКИ ЗДЕСЬ
	// Например: result := decrypt(happLink)
	
	fmt.Println(happLink) // Пока просто выводим обратно для теста
}
